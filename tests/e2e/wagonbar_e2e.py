"""End-to-end tests for the SNCF Voucher Reminder Firefox extension.

Drives a real headless Firefox via Marionette, installs the extension as a
temporary add-on, and verifies the full stack: manifest load, popup logic
(real popup.js against a mocked browser.storage), storage backend, and the
toolbar icon badge showing the number of valid vouchers.

Usage:
    python tests/e2e/wagonbar_e2e.py a    # install + empty badge + popup logic
    python tests/e2e/wagonbar_e2e.py b    # seeded storage + badge count
    python tests/e2e/wagonbar_e2e.py c    # Chromium load smoke (build + Edge)

Requires:
    - Firefox 121+ (Manifest V3 background event page) reachable as
      ``firefox.exe`` on PATH or by full path via the FIREFOX_BIN env var
    - ``pip install marionette_driver``
    - pwsh (PowerShell 7) for orphan-process cleanup on Windows
    - phase c only: a Chromium browser — Edge at its standard Windows
      location (or any Chromium executable via CHROME_BIN)

Notes:
    - Each phase launches its own disposable Firefox profile and cleans up
      afterwards; only headless instances started with -marionette are ever
      killed (the user's own Firefox is never touched).
    - The popup is tested in a localhost-served copy of popup.html with a
      shim for browser.storage because Firefox blocks automation of real
      extension pages (privileged browsing context).
    - The badge is read through Marionette's chrome context from the
      extension's toolbar button. A fresh profile parks extension buttons
      in the unified-extensions panel (whose DOM is built lazily and not
      reachable headlessly), so the profile is seeded with a saved
      CustomizableUI state that pins the button to the nav-bar.
    - Phase B seeds browser.storage.local by writing the extension's
      storage.js JSON file directly (legacy backend forced via
      extensions.webextensions.ExtensionStorageIDB.enabled=false, set before
      install); the backend caches after first read, so per-scenario storage
      changes require a fresh browser session.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import quote
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT_DIR = os.path.join(REPO, "extension")
POPUP_DIR = os.path.join(EXT_DIR, "popup")
ADDON_ID = "wagonbar@scabon.com"
WIDGET_ID = "wagonbar_scabon_com-browser-action"  # makeWidgetId(ADDON_ID)
BADGE_BTN_ID = "wagonbar_scabon_com-BAP"          # toolbar button inside the widget
IDB_PREF = "extensions.webextensions.ExtensionStorageIDB.enabled"
FIREFOX_BIN = os.environ.get("FIREFOX_BIN", "firefox.exe")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    line = ("PASS " if cond else "FAIL ") + name
    if detail:
        line += "  | " + str(detail)
    print(line, flush=True)


def build_xpi():
    xpi = os.path.join(tempfile.gettempdir(), "wagonbar-e2e-%d.xpi" % os.getpid())
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(EXT_DIR):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, EXT_DIR).replace("\\", "/"))
    return xpi


def kill_orphan_ff():
    # only headless instances started with -marionette (ours), never the user's browser
    if os.name != "nt":
        return
    subprocess.run(
        ["pwsh", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='firefox.exe'\" | "
         "Where-Object { $_.CommandLine -like '*-marionette*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
        capture_output=True, timeout=60)


class Session:
    def __init__(self, seed_vouchers=None):
        self.profile = tempfile.mkdtemp(prefix="wagonbar-ff-e2e-")
        self.xpi = build_xpi()
        # Pin the extension's toolbar button to the nav-bar so the badge is
        # readable from chrome context (fresh profiles park extension
        # buttons in the lazily-built unified-extensions panel).
        placement = {"placements": {"nav-bar": [WIDGET_ID]}}
        with open(os.path.join(self.profile, "prefs.js"), "w", encoding="utf-8") as fh:
            fh.write('user_pref("browser.uiCustomization.state", %s);\n'
                     % json.dumps(json.dumps(placement)))
        if seed_vouchers is not None:
            d = os.path.join(self.profile, "browser-extension-data", ADDON_ID)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "storage.js"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"vouchers": seed_vouchers}))
        self.proc = subprocess.Popen(
            [FIREFOX_BIN, "-marionette", "-headless", "-no-remote",
             "-profile", self.profile, "-remote-allow-system-access"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from marionette_driver.marionette import Marionette
        from marionette_driver.addons import Addons
        self.client = None
        last = None
        for _ in range(60):
            try:
                self.client = Marionette(host="127.0.0.1", port=2828)
                self.client.start_session()
                break
            except Exception as e:
                last = e
                self.client = None
                time.sleep(0.5)
        if self.client is None:
            raise RuntimeError("marionette session failed: %s" % last)
        # force the legacy JSONFile storage backend so storage.js seeding works
        self.client.set_pref(IDB_PREF, False)
        self.addon_id = Addons(self.client).install(self.xpi, temp=True)
        self.base = None
        for _ in range(20):
            raw = self.client.get_pref("extensions.webextensions.uuids")
            if raw:
                uuids = json.loads(raw)
                if ADDON_ID in uuids:
                    self.base = "moz-extension://" + uuids[ADDON_ID] + "/"
                    break
            time.sleep(0.5)

    def page_js(self, js):
        return self.client.execute_script(js)

    def close(self):
        try:
            self.client.quit()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        kill_orphan_ff()
        shutil.rmtree(self.profile, ignore_errors=True)
        try:
            os.remove(self.xpi)
        except OSError:
            pass


def badge_text(s):
    """Read the badge text from the extension's toolbar button (chrome context).

    Returns '' when the button exists but has no badge, None when the
    button is not in the toolbar DOM at all.
    """
    s.client.set_context(s.client.CONTEXT_CHROME)
    try:
        return s.client.execute_script(
            "let win = Services.wm.getMostRecentWindow('navigator:browser');"
            "let btn = win.document.getElementById(%s);"
            "return btn ? (btn.getAttribute('badge') || '') : null;"
            % json.dumps(BADGE_BTN_ID)
        )
    finally:
        s.client.set_context(s.client.CONTEXT_CONTENT)


def wait_for_badge(s, expected, timeout=30):
    deadline = time.time() + timeout
    value = None
    while time.time() < deadline:
        try:
            value = badge_text(s)
        except Exception as e:
            value = "ERR:" + str(e)
        if value == expected:
            return True
        time.sleep(0.5)
    return False


SHIM = """
(function(){
  var root = document.documentElement;
  // Loading the page with ?e2e-seed=<json> starts storage with legacy
  // vouchers (Marionette scripts run sandboxed and cannot reach page
  // globals, so the seed is passed through the URL instead)
  var seed = [];
  try {
    var m = /e2e-seed=([^&]+)/.exec(location.search);
    if (m) seed = JSON.parse(decodeURIComponent(m[1]));
  } catch (e) {}
  var alerts = [];
  var confirms = [];
  function clone(x){ return JSON.parse(JSON.stringify(x)); }
  var umbrella = [];
  function fire(area, changes){
    setTimeout(function(){
      umbrella.forEach(function(l){ try { l(clone(changes), area); } catch(e){} });
    }, 0);
  }
  // A mock storage area that fires change events (oldValue/newValue per
  // key), mirroring browser.storage semantics for the sync tests
  function makeArea(name, initial, attrs){
    var store = initial;
    var listeners = [];
    function refresh(){
      attrs.forEach(function(a){
        root.setAttribute(a[0], JSON.stringify(a[1]()));
      });
    }
    function notify(changes){
      setTimeout(function(){
        listeners.forEach(function(l){ try { l(clone(changes), name); } catch(e){} });
      }, 0);
      fire(name, changes);
    }
    return {
      get: function(k){ return Promise.resolve(clone(store)); },
      set: function(obj){
        var changes = {};
        Object.keys(obj).forEach(function(k){
          changes[k] = { oldValue: (k in store) ? clone(store[k]) : undefined,
                          newValue: clone(obj[k]) };
        });
        Object.assign(store, obj);
        refresh();
        notify(changes);
        return Promise.resolve();
      },
      remove: function(keys){
        var arr = Array.isArray(keys) ? keys : [keys];
        var changes = {};
        arr.forEach(function(k){
          changes[k] = { oldValue: (k in store) ? clone(store[k]) : undefined,
                          newValue: undefined };
          delete store[k];
        });
        refresh();
        notify(changes);
        return Promise.resolve();
      },
      getBytesInUse: function(){ return Promise.resolve(0); },
      onChanged: { addListener: function(l){ listeners.push(l); },
                   removeListener: function(l){
                     var i = listeners.indexOf(l);
                     if (i >= 0) listeners.splice(i, 1);
                   } }
    };
  }
  var localStore = { vouchers: seed };
  var syncStore = {};
  var localArea = makeArea('local', localStore, [
    ['data-e2e-store', function(){ return localStore.vouchers || []; }],
    ['data-e2e-device', function(){ return localStore.deviceId || ''; }]
  ]);
  var syncArea = makeArea('sync', syncStore, [
    ['data-e2e-sync-store', function(){ return syncStore; }]
  ]);
  window.alert = function(m){ alerts.push(String(m));
    root.setAttribute('data-e2e-alerts', JSON.stringify(alerts)); };
  window.confirm = function(){ confirms.push('called');
    root.setAttribute('data-e2e-confirms', JSON.stringify(confirms));
    return true; };
  window.browser = {
    storage: {
      local: localArea,
      sync: syncArea,
      onChanged: { addListener: function(l){ umbrella.push(l); },
                   removeListener: function(l){
                     var i = umbrella.indexOf(l);
                     if (i >= 0) umbrella.splice(i, 1);
                   } }
    },
    action: {
      setBadgeText: function(d){
        root.setAttribute('data-e2e-badge', (d && d.text) ? d.text : '');
        return Promise.resolve();
      },
      setBadgeBackgroundColor: function(){ return Promise.resolve(); },
      setBadgeTextColor: function(){ return Promise.resolve(); }
    }
  };
  // Test channel for the sync area: Marionette scripts cannot call page
  // functions, so commands travel through a DOM attribute + event
  document.addEventListener('e2e-sync-cmd', function(){
    var cmd = {};
    try { cmd = JSON.parse(root.getAttribute('data-e2e-sync-cmd') || '{}'); } catch(e){}
    if (cmd.op === 'set') syncArea.set(cmd.items);
    else if (cmd.op === 'remove') syncArea.remove(cmd.keys);
  });
  root.setAttribute('data-e2e-store', JSON.stringify(seed));
  root.setAttribute('data-e2e-sync-store', '{}');
  root.setAttribute('data-e2e-device', '');
  root.setAttribute('data-e2e-alerts', JSON.stringify(alerts));
  root.setAttribute('data-e2e-confirms', JSON.stringify(confirms));
  root.setAttribute('data-e2e-badge', '');
})();
"""


def build_popup_test_page(port):
    d = tempfile.mkdtemp(prefix="wagonbar-popup-test-")
    for f in ("popup.css", "popup.js"):
        shutil.copy(os.path.join(POPUP_DIR, f), os.path.join(d, f))
    # the test page runs the whole stack: popup + badge logic + the sync
    # engine, all against the storage shim below
    shutil.copy(os.path.join(EXT_DIR, "shared", "sync-common.js"),
                os.path.join(d, "sync-common.js"))
    shutil.copy(os.path.join(EXT_DIR, "background", "background.js"),
                os.path.join(d, "background.js"))
    shutil.copy(os.path.join(EXT_DIR, "background", "sync.js"),
                os.path.join(d, "sync.js"))
    html = open(os.path.join(POPUP_DIR, "popup.html"), encoding="utf-8").read()
    # the vendor polyfill and the shared script only run inside a real
    # extension; the test page runs against the shim instead (the shared
    # script is re-injected after it, with test-page-relative paths)
    html = html.replace('  <script src="../vendor/browser-polyfill.js"></script>\n', '')
    html = html.replace('  <script src="../shared/sync-common.js"></script>\n', '')
    # The real popup is exactly as wide as the container (350px); constrain
    # the test page the same way so wrapping matches the popup
    html = html.replace('<link rel="stylesheet" href="popup.css">',
                        '<link rel="stylesheet" href="popup.css">'
                        '<style>body{max-width:350px}</style>')
    shim_tag = "<script>%s</script>" % SHIM
    html = html.replace("<script src=\"popup.js\"></script>",
                        shim_tag + "\n  <script src=\"sync-common.js\"></script>"
                        + "\n  <script src=\"background.js\"></script>"
                        + "\n  <script src=\"sync.js\"></script>"
                        + "\n  <script src=\"popup.js\"></script>")
    with open(os.path.join(d, "test-popup.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    return d, "http://127.0.0.1:%d/test-popup.html" % port


def pstate(s):
    return json.loads(s.page_js(
        "return JSON.stringify({"
        " items: Array.from(document.querySelectorAll('.voucher-item')).map(function(e)"
        "   {return {cls: e.className, text: e.innerText.replace(/\\s+/g,' ').trim()};}),"
        " total: document.getElementById('totalVouchers').textContent,"
        " valid: document.getElementById('validVouchers').textContent,"
        " empty: document.getElementById('voucherList').innerText.trim(),"
        " alerts: JSON.parse(document.documentElement.getAttribute('data-e2e-alerts') || '[]'),"
        " confirms: JSON.parse(document.documentElement.getAttribute('data-e2e-confirms') || '[]'),"
        " status: (function(){ var s = document.getElementById('statusMessage');"
        "          return { hidden: s.hidden, text: s.textContent }; })(),"
        " store: JSON.parse(document.documentElement.getAttribute('data-e2e-store') || '[]'),"
        " syncStore: JSON.parse(document.documentElement.getAttribute('data-e2e-sync-store') || '{}'),"
        " badge: document.documentElement.getAttribute('data-e2e-badge') || '',"
        " deviceId: (function(){ var v = document.documentElement.getAttribute('data-e2e-device') || '';"
        "            try { return JSON.parse(v); } catch (e) { return ''; } })()"
        "});"
    ))


def popup_add(s, code, date):
    s.page_js(
        "document.getElementById('voucherCode').value = %s;"
        "document.getElementById('expiryDate').value = %s;"
        "document.getElementById('addVoucherForm').dispatchEvent("
        "  new Event('submit', {bubbles: true, cancelable: true}));"
        "return 'ok';" % (json.dumps(code), json.dumps(date))
    )


def popup_tests(s):
    port = 18345
    d, url = build_popup_test_page(port)
    httpd = None

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

    class Server(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        httpd = Server(("127.0.0.1", port), lambda *a, **kw: QuietHandler(*a, directory=d, **kw))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        s.client.navigate(url)
        time.sleep(1)

        st = pstate(s)
        check("popup: empty state (0 total, 0 valid, empty message)",
              st["total"] == "0" and st["valid"] == "0"
              and "No vouchers yet" in st["empty"], st["empty"])

        popup_add(s, "", "")  # empty fields -> inline error, no native alert
        time.sleep(0.5)
        st = pstate(s)
        check("popup: empty submit shows inline error, no native dialog",
              not st["status"]["hidden"]
              and "fill in both fields" in st["status"]["text"]
              and st["alerts"] == [] and st["confirms"] == [], st["status"])

        # errors are not transient: they must stay until the next action
        time.sleep(4.5)
        st = pstate(s)
        check("popup: errors stay until the next action (no auto-dismiss)",
              not st["status"]["hidden"]
              and "fill in both fields" in st["status"]["text"], st["status"])

        # an expired voucher can no longer be created through the form; load
        # the page again with one seeded directly into storage (as legacy
        # data) so expired rendering, sorting and the valid counter stay
        # covered
        expired_seed = [{"id": "seed-expired-1", "code": "E2E-EXPIRED-1",
                         "expiryDate": "2020-01-01",
                         "createdAt": "2026-09-29T00:00:00.000Z"}]
        s.client.navigate(url + "?e2e-seed=" + quote(json.dumps(expired_seed)))
        time.sleep(1)

        soon = date.today() + timedelta(days=7)
        soon_d = soon.strftime("%Y-%m-%d")
        popup_add(s, "E2E-FUTURE-999", "2028-06-30")
        popup_add(s, "E2E-SOON-111", soon_d)
        time.sleep(1)

        st = pstate(s)
        codes = [i["text"].split("Expires")[0].strip() for i in st["items"]]
        check("popup: 3 vouchers sorted oldest-first",
              codes == ["E2E-EXPIRED-1", "E2E-SOON-111", "E2E-FUTURE-999"], codes)
        check("popup: totals 3 total / 2 valid",
              st["total"] == "3" and st["valid"] == "2", (st["total"], st["valid"]))
        cls = [i["cls"] for i in st["items"]]
        check("popup: expired vs valid color-coding",
              "expired" in cls[0] and "valid" in cls[1] and "expired" not in cls[1], cls)
        check("popup: expiry date rendered YYYY-MM-DD",
              ("Expires: " + soon_d) in st["items"][1]["text"], st["items"][1]["text"])
        check("popup: no dialogs during normal adds",
              st["alerts"] == [] and st["confirms"] == [], (st["alerts"], st["confirms"]))

        popup_add(s, "E2E-SOON-111", "2027-01-01")  # duplicate code
        time.sleep(0.8)
        st = pstate(s)
        check("popup: duplicate code rejected inline, nothing added",
              len(st["items"]) == 3 and not st["status"]["hidden"]
              and "already exists" in st["status"]["text"]
              and st["alerts"] == [], (st["status"], st["alerts"]))

        # delete is a two-step action: first click arms the button
        s.page_js("document.querySelector('.voucher-item .delete-btn').click(); return 'ok';")
        time.sleep(0.4)
        st = pstate(s)
        check("popup: first delete click arms confirm state, no native dialog",
              len(st["items"]) == 3 and "Confirm?" in st["items"][0]["text"]
              and st["confirms"] == [], st["items"][0]["text"])

        s.page_js("document.querySelector('.voucher-item .delete-btn').click(); return 'ok';")
        gone = False
        for _ in range(20):
            st = pstate(s)
            if len(st["items"]) == 2:
                gone = True
                break
            time.sleep(0.4)
        store_codes = [v["code"] for v in st["store"]]
        check("popup: second click deletes voucher, list re-renders",
              gone and store_codes == ["E2E-SOON-111", "E2E-FUTURE-999"]
              and st["confirms"] == [] and st["alerts"] == [],
              (store_codes, st["confirms"], st["alerts"]))

        # the date is a text field (the native picker cannot open in a popup):
        # impossible dates are rejected inline, nothing added
        popup_add(s, "E2E-BAD-1", "2028-02-31")  # February 31st
        time.sleep(0.6)
        st = pstate(s)
        check("popup: impossible date rejected inline, nothing added",
              len(st["items"]) == 2 and not st["status"]["hidden"]
              and "valid expiration date" in st["status"]["text"]
              and st["alerts"] == [], (st["status"], st["alerts"]))

        # a date in the past is rejected (today is the earliest allowed)
        popup_add(s, "E2E-PAST-1", "2020-01-01")
        time.sleep(0.6)
        st = pstate(s)
        check("popup: past date rejected inline, nothing added",
              len(st["items"]) == 2 and not st["status"]["hidden"]
              and "in the past" in st["status"]["text"]
              and st["alerts"] == [], (st["status"], st["alerts"]))

        # clear the rejected date so the calendar opens on the current month
        s.page_js("var i = document.getElementById('expiryDate');"
                  "i.value = ''; i.dispatchEvent(new Event('input')); return 'ok';")

        # custom calendar widget: icon opens a month grid, picking a day
        # fills the field and closes the grid
        s.page_js("document.getElementById('calendarToggle').click(); return 'ok';")
        time.sleep(0.4)
        cal = json.loads(s.page_js(
            "var p = document.getElementById('calendarPanel');"
            "return JSON.stringify({hidden: p.hidden,"
            " days: p.querySelectorAll('.calendar-day').length,"
            " title: p.querySelector('.calendar-title').textContent});"
        ))
        now = time.localtime()
        check("calendar: icon opens month grid for the current month",
              cal["hidden"] is False and 28 <= cal["days"] <= 31
              and str(now.tm_year) in cal["title"], cal)

        # days before today cannot be picked; today stays selectable
        cal_dis = json.loads(s.page_js(
            "var p = document.getElementById('calendarPanel');"
            "return JSON.stringify({"
            " pastDisabled: p.querySelectorAll('.calendar-day:disabled').length,"
            " todayDisabled: p.querySelector('.calendar-day.today').disabled});"
        ))
        check("calendar: past days disabled, today still selectable",
              cal_dis["pastDisabled"] == now.tm_mday - 1
              and cal_dis["todayDisabled"] is False, cal_dis)

        s.page_js(
            "document.getElementById('calendarPanel')"
            ".querySelectorAll('.calendar-day')[14].click(); return 'ok';"
        )
        time.sleep(0.3)
        cal = json.loads(s.page_js(
            "var p = document.getElementById('calendarPanel');"
            "return JSON.stringify({hidden: p.hidden,"
            " value: document.getElementById('expiryDate').value});"
        ))
        picked = "%d-%02d-15" % (now.tm_year, now.tm_mon)
        check("calendar: picking a day fills the field YYYY-MM-DD and closes",
              cal["hidden"] is True and cal["value"] == picked, cal)

        # the calendar-picked date goes through the form submit as ISO storage
        popup_add(s, "E2E-PICKED-1", picked)
        time.sleep(0.6)
        st = pstate(s)
        picked_iso = "%d-%02d-15" % (now.tm_year, now.tm_mon)
        check("popup: calendar-picked date accepted on submit (ISO storage)",
              len(st["items"]) == 3
              and any(v["code"] == "E2E-PICKED-1"
                      and v["expiryDate"] == picked_iso for v in st["store"]),
              (st["store"], picked_iso))

        # date entry: digits are auto-dashed (the dash appears as soon as
        # the year or month is complete) and the remaining format is kept
        # visible as a grey hint behind the typed text
        s.page_js("var i = document.getElementById('expiryDate');"
                  "i.value = '2026'; i.dispatchEvent(new Event('input')); return 'ok';")
        time.sleep(0.2)
        st = json.loads(s.page_js(
            "var g = document.getElementById('expiryGhost');"
            "return JSON.stringify({"
            " value: document.getElementById('expiryDate').value,"
            " ghostRest: g.querySelector('.ghost-rest') ?"
            "   g.querySelector('.ghost-rest').textContent : null});"
        ))
        check("popup: dash appended after the year, grey hint keeps format",
              st["value"] == "2026-" and st["ghostRest"] == "MM-DD", st)

        s.page_js("var i = document.getElementById('expiryDate');"
                  "i.value = '20261015'; i.dispatchEvent(new Event('input')); return 'ok';")
        time.sleep(0.2)
        st = json.loads(s.page_js(
            "return JSON.stringify({"
            " value: document.getElementById('expiryDate').value,"
            " ghostRest: (document.getElementById('expiryGhost')"
            "   .querySelector('.ghost-rest') || {}).textContent || null});"
        ))
        check("popup: typed digits auto-dashed to YYYY-MM-DD, hint cleared",
              st["value"] == "2026-10-15" and st["ghostRest"] is None, st)

        # paste artifacts: leading/trailing spaces and line returns are trimmed
        popup_add(s, "  E2E-TRIM-1 \n", "2027-03-01")
        time.sleep(0.6)
        st = pstate(s)
        check("popup: pasted code trimmed of spaces/newlines",
              any(v["code"] == "E2E-TRIM-1" for v in st["store"]), st["store"])

        # usual 9-character code: saved without any warning
        popup_add(s, "GPLI089N3", "2027-03-02")
        time.sleep(0.6)
        st = pstate(s)
        check("popup: usual-length code saved without warning",
              st["status"]["hidden"]
              and any(v["code"] == "GPLI089N3" for v in st["store"]),
              (st["status"], st["store"]))

        # odd-length code: warning appears when focus leaves the code field,
        # and the save is never blocked; showing/clearing a message must
        # never change the popup size
        size = lambda: s.page_js(
            "return [document.body.offsetWidth, document.body.offsetHeight];")
        size_base = size()
        s.page_js("var c = document.getElementById('voucherCode');"
                   "c.value = 'TOOLONGCODE'; c.dispatchEvent(new Event('blur'));"
                   "return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        check("popup: odd-length code warns when focus leaves the field",
              not st["status"]["hidden"] and "usual" in st["status"]["text"],
              st["status"])
        size_warn = size()
        check("popup: popup size unchanged while the warning shows",
              size_warn == size_base, (size_base, size_warn))

        # a very long code is truncated in the warning so the message
        # can never overflow the reserved space
        s.page_js("var c = document.getElementById('voucherCode');"
                   "c.value = 'E2E-VERY-LONG-CODE-12345';"
                   "c.dispatchEvent(new Event('blur')); return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        size_trunc = size()
        check("popup: long code truncated in the warning, size still stable",
              not st["status"]["hidden"]
              and "\u2026" in st["status"]["text"]
              and "E2E-VERY-LONG-CODE-12345" not in st["status"]["text"]
              and size_trunc == size_base,
              (st["status"], size_base, size_trunc))

        # transient messages can be clicked away and auto-expire
        s.page_js("document.getElementById('statusMessage').click(); return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        check("popup: status dismissible by click",
              st["status"]["hidden"], st["status"])

        s.page_js("var c = document.getElementById('voucherCode');"
                   "c.value = 'TOOLONGCODE'; c.dispatchEvent(new Event('blur'));"
                   "return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        check("popup: warning shows again after being dismissed",
              not st["status"]["hidden"]
              and "TOOLONGCODE" in st["status"]["text"], st["status"])
        time.sleep(4.5)
        st = pstate(s)
        check("popup: warning auto-dismisses after a few seconds",
              st["status"]["hidden"], st["status"])

        popup_add(s, "TOOLONGCODE", "2027-03-03")
        time.sleep(0.6)
        st = pstate(s)
        check("popup: odd-length code saved anyway, warning cleared",
              any(v["code"] == "TOOLONGCODE" for v in st["store"])
              and st["status"]["hidden"],
              (st["status"], st["store"]))

        # edit: loading a voucher into the form and saving the changes
        def form_state():
            return json.loads(s.page_js(
                "return JSON.stringify({"
                " code: document.getElementById('voucherCode').value,"
                " date: document.getElementById('expiryDate').value,"
                " submit: document.getElementById('submitBtn').textContent,"
                " cancelHidden: document.getElementById('cancelEditBtn').hidden});"
            ))

        idx = next(i for i, it in enumerate(st["items"]) if "GPLI089N3" in it["text"])
        s.page_js("document.querySelectorAll('.voucher-item .edit-btn')[%d].click();"
                  "return 'ok';" % idx)
        time.sleep(0.4)
        fst = form_state()
        check("popup: edit loads voucher into the form",
              fst["code"] == "GPLI089N3" and fst["date"] == "2027-03-02"
              and fst["submit"] == "Update Voucher"
              and fst["cancelHidden"] is False, fst)

        # unchanged code must not count as a duplicate of itself
        popup_add(s, "GPLI089N3", "2027-04-01")
        time.sleep(0.6)
        st = pstate(s)
        fst = form_state()
        size_saved = size()
        check("popup: edited voucher updated in place, success shown",
              any(v["code"] == "GPLI089N3" and v["expiryDate"] == "2027-04-01"
                  for v in st["store"])
              and len(st["store"]) == 6
              and not st["status"]["hidden"]
              and "updated" in st["status"]["text"].lower()
              and fst["code"] == "" and fst["submit"] == "Add Voucher"
              and fst["cancelHidden"] is True,
              (st["status"], fst, st["store"]))
        check("popup: popup size unchanged after the success message",
              size_saved == size_base, (size_base, size_saved))

        # cancel leaves edit mode without touching anything
        s.page_js("document.querySelectorAll('.voucher-item .edit-btn')[%d].click();"
                  "return 'ok';" % idx)
        time.sleep(0.4)
        s.page_js("document.getElementById('cancelEditBtn').click(); return 'ok';")
        time.sleep(0.2)
        fst = form_state()
        st = pstate(s)
        check("popup: cancel exits edit mode and clears the form",
              fst["code"] == "" and fst["date"] == ""
              and fst["submit"] == "Add Voucher" and fst["cancelHidden"] is True
              and any(v["code"] == "GPLI089N3" and v["expiryDate"] == "2027-04-01"
                      for v in st["store"]),
              (fst, st["store"]))

        # sorting: by expiration date by default, switchable to by code,
        # and the choice is kept across renders
        def list_codes():
            st = pstate(s)
            return [i["text"].split("Expires")[0].strip() for i in st["items"]]

        check("popup: vouchers sorted by expiration date by default",
              list_codes() == ["E2E-PICKED-1", "E2E-SOON-111", "E2E-TRIM-1",
                               "TOOLONGCODE", "GPLI089N3", "E2E-FUTURE-999"],
              list_codes())

        s.page_js("var s = document.getElementById('sortOrder');"
                   "s.value = 'code'; s.dispatchEvent(new Event('change'));"
                   "return 'ok';")
        time.sleep(0.4)
        check("popup: sorting by code reorders the list",
              list_codes() == ["E2E-FUTURE-999", "E2E-PICKED-1", "E2E-SOON-111",
                               "E2E-TRIM-1", "GPLI089N3", "TOOLONGCODE"],
              list_codes())

        popup_add(s, "E2E-AAFIRST-1", "2029-01-01")
        time.sleep(0.6)
        check("popup: code sort kept after adding a voucher",
              list_codes() == ["E2E-AAFIRST-1", "E2E-FUTURE-999", "E2E-PICKED-1",
                               "E2E-SOON-111", "E2E-TRIM-1", "GPLI089N3",
                               "TOOLONGCODE"],
              list_codes())

        # a voucher expiring today counts as valid through the end of its
        # expiry day (date-only strings must not be parsed as UTC, which
        # would make it look already expired depending on the timezone)
        s.client.navigate(url)
        time.sleep(1)
        today_d = date.today().isoformat()
        popup_add(s, "E2E-TODAY-1", today_d)
        time.sleep(0.6)
        st = pstate(s)
        check("popup: voucher expiring today counts as valid",
              st["total"] == "1" and st["valid"] == "1"
              and "valid" in st["items"][0]["cls"]
              and "expired" not in st["items"][0]["cls"]
              and ("Expires: " + today_d) in st["items"][0]["text"],
              (st["total"], st["valid"], st["items"]))

        # ---- remove expired: bulk-clear button with the same two-step
        # confirm as the single delete ----
        def remove_expired_btn():
            return json.loads(s.page_js(
                "var b = document.getElementById('removeExpiredBtn');"
                "return JSON.stringify({hidden: b.hidden, text: b.textContent});"))

        s.client.navigate(url + "?e2e-seed=" + quote(json.dumps([
            {"id": "seed-rx-1", "code": "E2E-OLDEXP-1",
             "expiryDate": "2020-01-01",
             "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-rx-2", "code": "E2E-OLDEXP-2",
             "expiryDate": "2020-02-02",
             "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-rx-3", "code": "E2E-KEEPER-1",
             "expiryDate": "2028-01-01",
             "createdAt": "2026-09-29T00:00:00.000Z"}])))
        time.sleep(1)
        btn = remove_expired_btn()
        st = pstate(s)
        check("popup: remove-expired shown when an expired voucher exists",
              btn["hidden"] is False and btn["text"] == "Remove expired",
              (btn, st["total"], st["valid"]))

        s.page_js("document.getElementById('removeExpiredBtn').click(); return 'ok';")
        time.sleep(0.4)
        btn = remove_expired_btn()
        st = pstate(s)
        check("popup: first remove-expired click arms confirm, nothing deleted",
              btn["text"] == "Confirm?" and len(st["items"]) == 3
              and len(st["store"]) == 3, (btn, st["store"]))

        s.page_js("document.getElementById('removeExpiredBtn').click(); return 'ok';")
        removed = False
        for _ in range(20):
            st = pstate(s)
            if len(st["items"]) == 1:
                removed = True
                break
            time.sleep(0.4)
        store_codes = [v["code"] for v in st["store"]]
        tombstones = {k for k, v in st["syncStore"].items() if v.get("deleted")}
        btn = remove_expired_btn()
        check("popup: remove-expired clears expired, keeps valid, writes tombstones",
              removed and store_codes == ["E2E-KEEPER-1"]
              and not st["status"]["hidden"]
              and "Removed 2 expired vouchers" in st["status"]["text"]
              and tombstones == {"voucher-seed-rx-1", "voucher-seed-rx-2"},
              (store_codes, st["status"], st["syncStore"]))
        check("popup: remove-expired hides itself when nothing is expired",
              btn["hidden"] is True, btn)

        # ---- cross-device sync (the whole stack runs in the test page:
        # popup.js pushes user actions to the sync area, background sync
        # engine merges remote changes back into local storage) ----
        def sync_cmd(payload):
            # Marionette scripts run sandboxed: commands for the mocked
            # sync area travel through a DOM attribute + custom event
            s.page_js(
                "document.documentElement.setAttribute('data-e2e-sync-cmd', %s);"
                "document.dispatchEvent(new CustomEvent('e2e-sync-cmd'));"
                "return 'ok';" % json.dumps(json.dumps(payload)))

        def soon_ts(seconds):
            return (datetime.now(timezone.utc) + timedelta(seconds=seconds)
                    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # seeded local vouchers migrate into the sync area on startup
        s.client.navigate(url + "?e2e-seed=" + quote(json.dumps([
            {"id": "seed-sync-1", "code": "E2E-SEED-SYNC",
             "expiryDate": "2029-01-01",
             "createdAt": "2026-09-29T00:00:00.000Z"}])))
        time.sleep(1)
        st = pstate(s)
        rec = st["syncStore"].get("voucher-seed-sync-1")
        check("sync: existing local vouchers are pushed to sync on startup",
              rec is not None and rec.get("code") == "E2E-SEED-SYNC"
              and rec.get("by") == st["deviceId"], st["syncStore"])

        # a voucher added by the user mirrors to the sync area
        popup_add(s, "E2E-SYNC-1", "2027-12-01")
        time.sleep(0.9)
        st = pstate(s)
        rec = next((v for v in st["syncStore"].values()
                    if v.get("code") == "E2E-SYNC-1"), None)
        sync_key = next((k for k, v in st["syncStore"].items()
                         if v.get("code") == "E2E-SYNC-1"), None)
        check("sync: user add mirrors to the sync area per-voucher key",
              rec is not None and sync_key and sync_key.startswith("voucher-")
              and rec.get("expiryDate") == "2027-12-01"
              and rec.get("updatedAt") and rec.get("by") == st["deviceId"],
              st["syncStore"])

        # a voucher arriving from another device shows up without any
        # local user action (list, counters, badge)
        sync_cmd({"op": "set", "items": {"voucher-e2e-remote-1": {
            "id": "e2e-remote-1", "code": "E2E-REMOTE-1",
            "expiryDate": "2027-11-01",
            "createdAt": "2026-01-01T00:00:00.000Z",
            "updatedAt": soon_ts(60), "by": "e2e-other-device"}}})
        time.sleep(0.9)
        st = pstate(s)
        codes = [i["text"].split("Expires")[0].strip() for i in st["items"]]
        check("sync: remote voucher merges in and updates list, counters, badge",
              "E2E-REMOTE-1" in codes and st["total"] == "3"
              and st["valid"] == "3" and st["badge"] == "3",
              (codes, st["total"], st["valid"], st["badge"]))

        # a newer remote edit wins over the local copy
        sync_cmd({"op": "set", "items": {sync_key: {
            "id": sync_key[len("voucher-"):], "code": "E2E-SYNC-1",
            "expiryDate": "2028-01-01",
            "createdAt": "2026-01-01T00:00:00.000Z",
            "updatedAt": soon_ts(120), "by": "e2e-other-device"}}})
        time.sleep(0.9)
        st = pstate(s)
        check("sync: newer remote edit overwrites the local copy",
              any("E2E-SYNC-1" in i["text"] and "2028-01-01" in i["text"]
                  for i in st["items"])
              and any(v.get("expiryDate") == "2028-01-01" for v in st["store"]),
              st["items"])

        # a remote tombstone removes the voucher locally
        sync_cmd({"op": "set", "items": {sync_key: {
            "deleted": True,
            "updatedAt": soon_ts(180), "by": "e2e-other-device"}}})
        time.sleep(0.9)
        st = pstate(s)
        codes = [i["text"].split("Expires")[0].strip() for i in st["items"]]
        check("sync: remote tombstone removes the voucher locally",
              "E2E-SYNC-1" not in codes and st["total"] == "2",
              (codes, st["total"]))

        # deleting locally mirrors as a tombstone, not as a key removal
        s.page_js("var b = document.querySelector('.voucher-item .delete-btn');"
                  "b.click(); return 'ok';")
        time.sleep(0.4)
        s.page_js("var b = document.querySelector('.voucher-item .delete-btn');"
                  "if (b) b.click(); return 'ok';")
        time.sleep(1.0)
        st = pstate(s)
        tomb = st["syncStore"].get("voucher-e2e-remote-1")
        check("sync: local delete mirrors as a tombstone",
              tomb is not None and tomb.get("deleted") is True
              and tomb.get("by") == st["deviceId"]
              and st["total"] == "1",
              (st["syncStore"], st["total"]))
    finally:
        if httpd:
            httpd.shutdown()
        shutil.rmtree(d, ignore_errors=True)


def phase_a():
    s = Session(seed_vouchers=[])
    try:
        check("extension installs as temporary add-on (MV3 manifest accepted)",
              s.addon_id == ADDON_ID, s.addon_id)
        check("extension internal URL resolvable", bool(s.base), s.base)

        check("badge: empty (no badge) with no vouchers",
              wait_for_badge(s, ""), badge_text(s))

        popup_tests(s)
    finally:
        s.close()


def phase_b():
    vouchers = [
        {"id": "1", "code": "E2E-EXPIRED-1", "expiryDate": "2020-01-01",
         "createdAt": "2026-09-29T00:00:00.000Z"},
        {"id": "2", "code": "E2E-SOON-111",
         "expiryDate": (date.today() + timedelta(days=7)).isoformat(),
         "createdAt": "2026-09-29T00:00:00.000Z"},
        {"id": "3", "code": "E2E-FUTURE-999", "expiryDate": "2028-06-30",
         "createdAt": "2026-09-29T00:00:00.000Z"},
        # expires today: must still count as valid (same-day boundary)
        {"id": "4", "code": "E2E-TODAY-111", "expiryDate": date.today().isoformat(),
         "createdAt": "2026-09-29T00:00:00.000Z"},
    ]
    s = Session(seed_vouchers=vouchers)
    try:
        check("extension installs (phase B)", s.addon_id == ADDON_ID, s.addon_id)
        check("badge: shows count of valid vouchers (expired one filtered out, today kept)",
              wait_for_badge(s, "3"), badge_text(s))
    finally:
        s.close()


def phase_c():
    """Chromium load smoke: build the Chromium package and load it in
    headless Edge (or CHROME_BIN). The extension's service worker must
    start and show up as a DevTools target — proof that the generated
    manifest is accepted and the polyfill/SW wiring works on Chromium.

    The debug port is ephemeral and the browser process tree is killed
    with taskkill /T: Edge's real browser process survives a plain
    terminate() of the launcher, and an orphan holding the port makes
    the next run query the previous instance's targets."""
    subprocess.run([sys.executable, os.path.join(REPO, "tools", "build-chrome.py")],
                   check=True)
    build_dir = os.path.join(REPO, "dist", "chrome-unpacked")
    chrome_bin = os.environ.get("CHROME_BIN") or \
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(chrome_bin):
        chrome_bin = "chrome.exe"
    profile = tempfile.mkdtemp(prefix="wagonbar-chrome-smoke-")
    # pick a free port so a stale headless instance can never shadow it
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [chrome_bin, "--headless=new", "--no-first-run",
         "--no-default-browser-check", "--user-data-dir=" + profile,
         "--remote-debugging-port=%d" % port,
         "--load-extension=" + build_dir, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    targets = []
    try:
        for _ in range(60):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/list" % port, timeout=2) as r:
                    targets = json.load(r)
            except Exception:
                continue
            if any(t.get("type") == "service_worker" and
                   "background/service-worker.js" in t.get("url", "")
                   for t in targets):
                break
    finally:
        if os.name == "nt":
            # Edge's browser process outlives terminate() of the spawned
            # process; kill the whole tree so no orphan holds the port
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    sw_urls = [t.get("url") for t in targets
               if t.get("type") == "service_worker" and
               "background/service-worker.js" in t.get("url", "")]
    check("chrome: extension loads, service worker starts (headless Chromium)",
          bool(sw_urls), sw_urls or
          {"returncode": proc.returncode, "targets": targets[:5]})


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "a"
    if phase == "a":
        phase_a()
    elif phase == "b":
        phase_b()
    elif phase == "c":
        phase_c()
    else:
        print("usage: wagonbar_e2e.py [a|b|c]")
        return 2
    failed = [n for n, ok in RESULTS if not ok]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)), flush=True)
    for n in failed:
        print("FAILED: " + n, flush=True)
    return 1 if failed else 0


sys.exit(main())
