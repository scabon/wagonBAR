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
import calendar
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
  // Deterministic locale: the popup resolves "system" from the browser
  // locale (French if the browser is French, English otherwise), and the
  // suite asserts English strings, so pin the locale here
  try {
    Object.defineProperty(navigator, 'language',
                         { value: 'en-US', configurable: true });
    Object.defineProperty(navigator, 'languages',
                         { value: ['en-US'], configurable: true });
  } catch (e) {}
  // Loading the page with ?e2e-seed=<json> starts storage with legacy
  // vouchers (Marionette scripts run sandboxed and cannot reach page
  // globals, so the seed is passed through the URL instead)
  var seed = [];
  try {
    var m = /e2e-seed=([^&]+)/.exec(location.search);
    if (m) seed = JSON.parse(decodeURIComponent(m[1]));
  } catch (e) {}
  // optional initial settings (?e2e-settings=<json>, same encoding):
  // theme/language/notifications for popup.js loadSettings
  var settingsSeed = {};
  try {
    var ms = /e2e-settings=([^&]+)/.exec(location.search);
    if (ms) settingsSeed = JSON.parse(decodeURIComponent(ms[1]));
  } catch (e) {}
  // optional draft (?e2e-draft=<json>, same encoding): a half-filled
  // form left over from a previous popup instance, as saved by
  // saveDraft() in popup.js
  var draftSeed = null;
  try {
    var md2 = /e2e-draft=([^&]+)/.exec(location.search);
    if (md2) draftSeed = JSON.parse(decodeURIComponent(md2[1]));
  } catch (e) {}
  var alerts = [];
  var confirms = [];
  var notifLog = [];
  var notifClickListeners = [];
  var tabUpdatedListeners = [];
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
  var localStore = { vouchers: seed, settings: settingsSeed, draft: draftSeed };
  var syncStore = {};
  var localArea = makeArea('local', localStore, [
    ['data-e2e-store', function(){ return localStore.vouchers || []; }],
    ['data-e2e-device', function(){ return localStore.deviceId || ''; }],
    ['data-e2e-settings', function(){ return localStore.settings || {}; }],
    ['data-e2e-exp-notified', function(){ return localStore.expiryNotified || {}; }],
    ['data-e2e-exp-snooze', function(){ return localStore.expirySnooze || {}; }],
    ['data-e2e-draft', function(){ return localStore.draft || null; }]
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
    },
    notifications: {
      // real API signature: create(id, options); no id -> auto id
      create: function(idOrOpts, maybeOpts){
        var opts = maybeOpts || idOrOpts;
        var id = maybeOpts ? idOrOpts
                           : ('e2e-notif-' + (notifLog.length + 1));
        notifLog.push({id: id, title: opts.title, message: opts.message,
                       buttons: opts.buttons || null});
        root.setAttribute('data-e2e-notifications', JSON.stringify(notifLog));
        return Promise.resolve(id);
      },
      clear: function(){ return Promise.resolve(true); },
      getAll: function(){ return Promise.resolve({}); },
      onClicked: { addListener: function(l){ notifClickListeners.push(l); },
                   removeListener: function(l){
                     var i = notifClickListeners.indexOf(l);
                     if (i >= 0) notifClickListeners.splice(i, 1);
                   } },
      // Firefox DECLARES onButtonClicked in its schema (an Event that
      // never fires) while marking the buttons OPTION unsupported -
      // passing buttons to create() rejects on the real Firefox surface.
      // Exposed here so a buttons regression fails the "no buttons"
      // check instead of silently passing like a button-less mock would.
      onButtonClicked: { addListener: function(){}, removeListener: function(){} }
    },
    tabs: {
      onUpdated: { addListener: function(l){ tabUpdatedListeners.push(l); },
                    removeListener: function(){} },
      onRemoved: { addListener: function(){}, removeListener: function(){} }
    },
    // alarms: enough surface for background/expiry-notify.js to register
    // its daily timer in the test page (the check itself is driven by
    // storage change events, like the sync engine)
    alarms: {
      create: function(){ return Promise.resolve(); },
      clear: function(){ return Promise.resolve(true); },
      onAlarm: { addListener: function(){}, removeListener: function(){} }
    },
    // Firefox surface: runtime.getURL exists, and so does
    // getBrowserInfo (Firefox-only) - expiry-notify.js uses its ABSENCE
    // to detect Chromium and switch on notification buttons
    runtime: {
      getURL: function(p){ return 'moz-extension://e2e/' + p; },
      getBrowserInfo: function(){
        return Promise.resolve({name: 'Firefox', version: '137.0'});
      }
    }
  };
  // Test channel for the sync area: Marionette scripts cannot call page
  // functions, so commands travel through a DOM attribute + event
  document.addEventListener('e2e-sync-cmd', function(){
    var cmd = {};
    try { cmd = JSON.parse(root.getAttribute('data-e2e-sync-cmd') || '{}'); } catch(e){}
    if (cmd.op === 'set') syncArea.set(cmd.items);
    else if (cmd.op === 'remove') syncArea.remove(cmd.keys);
    else if (cmd.op === 'local-set') localArea.set(cmd.items);
    else if (cmd.op === 'notif-click') {
      // simulate the user clicking a system notification
      notifClickListeners.forEach(function(l){ try { l(cmd.id); } catch(e){} });
    }
    else if (cmd.op === 'tab-complete') {
      // simulate a tab finishing a page load (what background/sncf-notify.js
      // listens to in a real browser)
      tabUpdatedListeners.forEach(function(l){
        try { l(cmd.tabId, {status: 'complete', url: cmd.url},
                   {id: cmd.tabId, url: cmd.url}); } catch(e){}
      });
    }
  });
  root.setAttribute('data-e2e-store', JSON.stringify(seed));
  root.setAttribute('data-e2e-sync-store', '{}');
  root.setAttribute('data-e2e-device', '');
  root.setAttribute('data-e2e-settings', JSON.stringify(settingsSeed));
  root.setAttribute('data-e2e-notifications', '[]');
  root.setAttribute('data-e2e-exp-notified', '{}');
  root.setAttribute('data-e2e-exp-snooze', '{}');
  root.setAttribute('data-e2e-draft', JSON.stringify(draftSeed));
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
    shutil.copy(os.path.join(EXT_DIR, "background", "sncf-notify.js"),
                os.path.join(d, "sncf-notify.js"))
    shutil.copy(os.path.join(EXT_DIR, "background", "expiry-notify.js"),
                os.path.join(d, "expiry-notify.js"))
    # the h1 icon: copy the PNG in and make the src test-page-relative
    # (the real popup's ../icons/ does not exist in the served dir)
    shutil.copy(os.path.join(EXT_DIR, "icons", "icon-48.png"),
                os.path.join(d, "icon-48.png"))
    html = open(os.path.join(POPUP_DIR, "popup.html"), encoding="utf-8").read()
    html = html.replace('../icons/icon-48.png', 'icon-48.png')
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
                        + "\n  <script src=\"sncf-notify.js\"></script>"
                        + "\n  <script src=\"expiry-notify.js\"></script>"
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
        " value: document.getElementById('validValue').textContent,"
        " empty: document.getElementById('voucherList').innerText.trim(),"
        " alerts: JSON.parse(document.documentElement.getAttribute('data-e2e-alerts') || '[]'),"
        " confirms: JSON.parse(document.documentElement.getAttribute('data-e2e-confirms') || '[]'),"
        " status: (function(){ var s = document.getElementById('statusMessage');"
        "          return { hidden: s.hidden, text: s.textContent }; })(),"
        " store: JSON.parse(document.documentElement.getAttribute('data-e2e-store') || '[]'),"
        " settings: JSON.parse(document.documentElement.getAttribute('data-e2e-settings') || '{}'),"
        " notifications: JSON.parse(document.documentElement.getAttribute('data-e2e-notifications') || '[]'),"
        " expNotified: JSON.parse(document.documentElement.getAttribute('data-e2e-exp-notified') || '{}'),"
        " expSnooze: JSON.parse(document.documentElement.getAttribute('data-e2e-exp-snooze') || '{}'),"
        " draft: JSON.parse(document.documentElement.getAttribute('data-e2e-draft') || 'null'),"
        " syncStore: JSON.parse(document.documentElement.getAttribute('data-e2e-sync-store') || '{}'),"
        " badge: document.documentElement.getAttribute('data-e2e-badge') || '',"
        " deviceId: (function(){ var v = document.documentElement.getAttribute('data-e2e-device') || '';"
        "            try { return JSON.parse(v); } catch (e) { return ''; } })()"
        "});"
    ))


def popup_add(s, code, date, value=None):
    # the add form is collapsed by default, like for a real user
    s.page_js(
        "if (document.getElementById('addVoucherForm').hidden)"
        "  document.getElementById('addToggleBtn').click(); return 'ok';")
    s.page_js(
        "document.getElementById('voucherCode').value = %s;"
        "document.getElementById('voucherValue').value = %s;"
        "document.getElementById('expiryDate').value = %s;"
        "document.getElementById('addVoucherForm').dispatchEvent("
        "  new Event('submit', {bubbles: true, cancelable: true}));"
        "return 'ok';" % (json.dumps(code),
                          json.dumps("" if value is None else value),
                          json.dumps(date))
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

        icon = json.loads(s.page_js(
            "var im = document.querySelector('h1 img');"
            "return JSON.stringify({present: !!im,"
            " loaded: !!im && im.complete && im.naturalWidth > 0,"
            " size: !!im && im.offsetWidth});"))
        check("popup: title carries the rendered extension icon",
              icon["present"] and icon["loaded"] and icon["size"] > 0, icon)

        addform = json.loads(s.page_js(
            "var f = document.getElementById('addVoucherForm'),"
            "    b = document.getElementById('addToggleBtn');"
            "return JSON.stringify({hidden: f.hidden, glyph: b.textContent,"
            " expanded: b.getAttribute('aria-expanded')});"))
        check("popup: add form collapsed by default behind the + button",
              addform["hidden"] is True and addform["glyph"] == "+"
              and addform["expanded"] == "false", addform)

        s.page_js("document.getElementById('addToggleBtn').click();"
                  "return 'ok';")
        time.sleep(0.2)
        addform = json.loads(s.page_js(
            "var f = document.getElementById('addVoucherForm'),"
            "    b = document.getElementById('addToggleBtn');"
            "return JSON.stringify({hidden: f.hidden, glyph: b.textContent,"
            " expanded: b.getAttribute('aria-expanded')});"))
        check("popup: the + button opens the form",
              addform["hidden"] is False and addform["glyph"] == "\u2212"
              and addform["expanded"] == "true", addform)
        s.page_js("document.getElementById('addToggleBtn').click();"
                  "return 'ok';")
        time.sleep(0.2)
        check("popup: the \u2212 button collapses the form again",
              s.page_js(
                  "return document.getElementById('addVoucherForm').hidden;") is True)

        sncf = json.loads(s.page_js(
            "var a = document.getElementById('sncfLink');"
            "return JSON.stringify({href: a.href, target: a.target,"
            " text: a.textContent.trim(), hidden: a.hidden});"))
        check("popup: SNCF Connect link hidden with no valid vouchers",
              sncf["href"] == "https://www.sncf-connect.com/"
              and sncf["target"] == "_blank"
              and sncf["text"] == "Use your vouchers on SNCF Connect"
              and sncf["hidden"] is True, sncf)

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
        check("popup: SNCF Connect link shown with a valid voucher",
              s.page_js(
                  "return document.getElementById('sncfLink').hidden;") is False)
        cls = [i["cls"] for i in st["items"]]
        check("popup: expired vs valid color-coding",
              "expired" in cls[0] and "valid" in cls[1] and "expired" not in cls[1], cls)
        check("popup: expiry date rendered YYYY-MM-DD",
              ("Expires: " + soon_d) in st["items"][1]["text"], st["items"][1]["text"])
        check("popup: no dialogs during normal adds",
              st["alerts"] == [] and st["confirms"] == [], (st["alerts"], st["confirms"]))
        check("popup: add form collapses again after a successful add",
              s.page_js(
                  "return document.getElementById('addVoucherForm').hidden;") is True)

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

        # pick a day that is always selectable: tomorrow, falling back to
        # today on the last day of the month (both are >= today, so the
        # pick is never a disabled past day whatever the run date)
        days_in_month = calendar.monthrange(now.tm_year, now.tm_mon)[1]
        pick_day = min(now.tm_mday + 1, days_in_month)
        s.page_js(
            "document.getElementById('calendarPanel')"
            ".querySelectorAll('.calendar-day')[%d].click(); return 'ok';" % (pick_day - 1)
        )
        time.sleep(0.3)
        cal = json.loads(s.page_js(
            "var p = document.getElementById('calendarPanel');"
            "return JSON.stringify({hidden: p.hidden,"
            " value: document.getElementById('expiryDate').value});"
        ))
        picked = "%d-%02d-%02d" % (now.tm_year, now.tm_mon, pick_day)
        check("calendar: picking a day fills the field YYYY-MM-DD and closes",
              cal["hidden"] is True and cal["value"] == picked, cal)

        # the calendar-picked date goes through the form submit as ISO storage
        popup_add(s, "E2E-PICKED-1", picked)
        time.sleep(0.6)
        st = pstate(s)
        check("popup: calendar-picked date accepted on submit (ISO storage)",
              len(st["items"]) == 3
              and any(v["code"] == "E2E-PICKED-1"
                      and v["expiryDate"] == picked for v in st["store"]),
              (st["store"], picked))

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
        # and the save is never blocked; showing/clearing a message may
        # change the popup height (the status slot is no longer
        # reserved), but never the width. The form is collapsed after
        # the previous successful add - open it first, a real user
        # cannot blur a field of a hidden form
        s.page_js("if (document.getElementById('addVoucherForm').hidden)"
                  "  document.getElementById('addToggleBtn').click();"
                  "return 'ok';")
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
        check("popup: width unchanged while the warning shows (height may grow)",
              size_warn[0] == size_base[0] and size_warn[1] >= size_base[1],
              (size_base, size_warn))

        # a very long code is truncated in the warning so the message
        # stays on a single line
        s.page_js("var c = document.getElementById('voucherCode');"
                   "c.value = 'E2E-VERY-LONG-CODE-12345';"
                   "c.dispatchEvent(new Event('blur')); return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        size_trunc = size()
        check("popup: long code truncated in the warning, width still stable",
              not st["status"]["hidden"]
              and "\u2026" in st["status"]["text"]
              and "E2E-VERY-LONG-CODE-12345" not in st["status"]["text"]
              and size_trunc[0] == size_base[0]
              and size_trunc[1] == size_warn[1],
              (st["status"], size_base, size_warn, size_trunc))

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
        check("popup: width unchanged after the success message",
              size_saved[0] == size_base[0], (size_base, size_saved))

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

        # ---- menu: Settings / Help / About views ----
        def view_state():
            return json.loads(s.page_js(
                "function h(i){return document.getElementById(i).hidden;}"
                "var ts = document.getElementById('themeSelect').value,"
                "    ls = document.getElementById('languageSelect').value,"
                "    nt = document.getElementById('notificationsToggle').checked,"
                "    et = document.getElementById('expiryNotificationsToggle').checked,"
                "    lg = document.getElementById('leadDaysGroup').hidden,"
                "    ld = document.getElementById('leadDaysInput').value;"
                "return JSON.stringify({main: h('view-main'),"
                " settings: h('view-settings'), help: h('view-help'), about: h('view-about'),"
                " theme: ts, lang: ls, notif: nt, expiry: et, leadHidden: lg, lead: ld});"))

        s.client.navigate(url)
        time.sleep(1)

        s.page_js("document.getElementById('menuBtn').click(); return 'ok';")
        time.sleep(0.3)
        menu = json.loads(s.page_js(
            "var m = document.getElementById('menuPanel');"
            "return JSON.stringify({hidden: m.hidden,"
            " entries: Array.from(m.querySelectorAll('button')).map(function(b)"
            "  {return b.textContent.replace(/\\s+/g, ' ').trim();})});"))
        check("menu: hamburger opens a menu with Settings/Help/About",
              menu["hidden"] is False
              and menu["entries"] == ["Settings", "Help", "About"], menu)

        s.page_js("document.getElementById('menuSettings').click(); return 'ok';")
        time.sleep(0.3)
        vs = view_state()
        check("menu: Settings view opens with system defaults",
              vs["main"] is True and vs["settings"] is False and vs["help"] is True
              and vs["about"] is True and vs["theme"] == "system"
              and vs["lang"] == "system" and vs["notif"] is True
              and vs["expiry"] is True and vs["leadHidden"] is False
              and vs["lead"] == "7", vs)

        s.page_js("var s = document.getElementById('themeSelect'); s.value = 'dark';"
                  "s.dispatchEvent(new Event('change')); return 'ok';")
        time.sleep(0.3)
        st = pstate(s)
        theme = s.page_js("return document.documentElement.getAttribute('data-theme');")
        check("menu: dark theme applies immediately and persists",
              theme == "dark" and st["settings"].get("theme") == "dark",
              (theme, st["settings"]))

        s.page_js("document.getElementById('notificationsToggle').click(); return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        check("menu: notifications toggle persists off",
              st["settings"].get("notifications") is False, st["settings"])

        s.page_js("document.getElementById('expiryNotificationsToggle').click();"
                  "return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        vs = view_state()
        check("menu: expiry-reminders checkbox persists off, lead days hidden",
              st["settings"].get("expiryNotifications") is False
              and vs["leadHidden"] is True,
              (st["settings"], vs))
        s.page_js("document.getElementById('expiryNotificationsToggle').click();"
                  "return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        vs = view_state()
        check("menu: expiry-reminders checkbox persists back on, lead days shown",
              st["settings"].get("expiryNotifications") is True
              and vs["leadHidden"] is False,
              (st["settings"], vs))

        s.page_js("var ld = document.getElementById('leadDaysInput');"
                  "ld.value = '3';"
                  "ld.dispatchEvent(new Event('change')); return 'ok';")
        time.sleep(0.2)
        st = pstate(s)
        check("menu: expiry lead days persist",
              st["settings"].get("notifyLeadDays") == 3, st["settings"])

        s.page_js("document.querySelector('#view-settings .back-btn').click(); return 'ok';")
        s.page_js("document.getElementById('menuBtn').click(); return 'ok';")
        s.page_js("document.getElementById('menuAbout').click(); return 'ok';")
        time.sleep(0.3)
        about = json.loads(s.page_js(
            "var c = document.getElementById('aboutContent');"
            "return JSON.stringify({"
            " name: c.querySelector('.about-name').textContent,"
            " version: c.querySelector('.about-version').textContent,"
            " madeBy: c.querySelector('.about-site').parentElement.textContent.trim(),"
            " links: Array.from(c.querySelectorAll('a')).map(function(a)"
            "  {return [a.className, a.href];})});"))
        # no browser.runtime in the test page, so the version stays empty.
        # Tipeee serves a French UI on fr.tipeee.com and an English one on
        # en.tipeee.com (same campaign): the English popup gets the EN link
        check("menu: About shows wagonBar and the EU donation links",
              about["name"] == "wagonBar" and about["version"] == ""
              and about["madeBy"] == "Made by: cabon14.com"
              and about["links"] == [["about-site", "https://cabon14.com/"],
                                    ["about-site", "mailto:support@cabon14.com"],
                                    ["donate-liberapay", "https://liberapay.com/cabon14/"],
                                    ["donate-tipeee", "https://en.tipeee.com/cabon14/"]],
              about)

        # the French UI gets the French Tipeee page (e2e-settings seeds
        # the language through the storage shim)
        s.client.navigate(url + "?e2e-settings=" + quote(json.dumps(
            {"language": "fr", "theme": "system", "notifications": True})))
        time.sleep(1)
        tipeee_fr = s.page_js(
            "return document.querySelector('#aboutContent .donate-tipeee').href;")
        liberapay_fr = s.page_js(
            "return document.querySelector('#aboutContent .donate-liberapay').href;")
        check("menu: French gets the fr.tipeee.com link, Liberapay unchanged",
              tipeee_fr == "https://fr.tipeee.com/cabon14/"
              and liberapay_fr == "https://liberapay.com/cabon14/",
              (tipeee_fr, liberapay_fr))
        s.client.navigate(url)
        time.sleep(1)

        s.page_js("document.querySelector('#view-about .back-btn').click(); return 'ok';")
        s.page_js("document.getElementById('menuBtn').click(); return 'ok';")
        s.page_js("document.getElementById('menuHelp').click(); return 'ok';")
        time.sleep(0.3)
        headings = json.loads(s.page_js(
            "return JSON.stringify(Array.from(document.querySelectorAll('#helpContent h2'))"
            ".map(function(h){return h.textContent;}));"))
        check("menu: Help lists the usage sections",
              headings == ["Adding a voucher", "Managing vouchers",
                           "Notifications", "Sync across devices",
                           "Privacy"], headings)

        # language switch to French, from the Settings view
        s.page_js("document.querySelector('#view-help .back-btn').click(); return 'ok';")
        s.page_js("document.getElementById('menuBtn').click(); return 'ok';")
        s.page_js("document.getElementById('menuSettings').click(); return 'ok';")
        s.page_js("var s = document.getElementById('languageSelect'); s.value = 'fr';"
                  "s.dispatchEvent(new Event('change')); return 'ok';")
        time.sleep(0.3)
        st = pstate(s)
        check("menu: French language persists to settings",
              st["settings"].get("language") == "fr", st["settings"])

        s.page_js("document.querySelector('#view-settings .back-btn').click(); return 'ok';")
        time.sleep(0.3)
        fr = json.loads(s.page_js(
            "return JSON.stringify({"
            " h1: document.querySelector('#view-main h1').textContent,"
            " empty: document.getElementById('voucherList').innerText.trim(),"
            " removeExpired: (function(){ var b = document.getElementById('removeExpiredBtn');"
            "  return {hidden: b.hidden, text: b.textContent}; })()});"))
        check("menu: French switches the main view strings",
              fr["h1"] == "wagonBar \u2014 Bons SNCF"
              and fr["empty"] == "Aucun bon pour l\u2019instant. Ajoutez-en un ci-dessus !"
              and fr["removeExpired"]["hidden"] is True, fr)

        # ---- SNCF site arrival notification (tabs/notifications are
        # mocked by the test-page shim) ----
        def page_cmd(payload):
            s.page_js(
                "document.documentElement.setAttribute('data-e2e-sync-cmd', %s);"
                "document.dispatchEvent(new CustomEvent('e2e-sync-cmd'));"
                "return 'ok';" % json.dumps(json.dumps(payload)))

        def tab_complete(tab_id, page_url):
            page_cmd({"op": "tab-complete", "tabId": tab_id, "url": page_url})

        s.client.navigate(url + "?e2e-seed=" + quote(json.dumps([
            {"id": "seed-n-1", "code": "E2E-NOTIF-1",
             "expiryDate": "2027-01-01",
             "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-n-2", "code": "E2E-NOTIF-2",
             "expiryDate": "2026-12-01",
             "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-n-3", "code": "E2E-OLDEXP-9",
             "expiryDate": "2020-01-01",
             "createdAt": "2026-09-29T00:00:00.000Z"}])))
        time.sleep(1)

        tab_complete(11, "https://www.sncf-connect.com/")
        time.sleep(0.8)
        st = pstate(s)
        days_to_nearest = (date(2026, 12, 1) - date.today()).days
        check("notify: SNCF arrival fires one notification with the valid count",
              len(st["notifications"]) == 1
              and st["notifications"][0]["title"] == "wagonBar"
              and "You have 2 valid vouchers" in st["notifications"][0]["message"]
              and "2026-12-01" in st["notifications"][0]["message"]
              and ("(in %d days)" % days_to_nearest)
              in st["notifications"][0]["message"],
              st["notifications"])

        tab_complete(11, "https://www.sncf-connect.com/")
        time.sleep(0.5)
        st = pstate(s)
        check("notify: repeat loads of the same visit stay silent",
              len(st["notifications"]) == 1, st["notifications"])

        tab_complete(11, "https://www.example.com/")
        tab_complete(11, "https://www.sncf-connect.com/mon-compte")
        time.sleep(0.8)
        st = pstate(s)
        check("notify: a new visit after leaving the site notifies again",
              len(st["notifications"]) == 2, st["notifications"])

        # the Settings toggle disables the notification
        page_cmd({"op": "local-set", "items":
                  {"settings": {"theme": "system", "language": "system",
                                "notifications": False}}})
        time.sleep(0.3)
        tab_complete(12, "https://app.sncf-connect.com/")
        time.sleep(0.8)
        st = pstate(s)
        check("notify: the settings toggle turns the notification off",
              len(st["notifications"]) == 2, st["notifications"])

        # a tab with no valid vouchers never notifies
        page_cmd({"op": "local-set", "items":
                  {"settings": {"theme": "system", "language": "system",
                                "notifications": True},
                   "vouchers": [{"id": "seed-n-3", "code": "E2E-OLDEXP-9",
                                 "expiryDate": "2020-01-01",
                                 "createdAt": "2026-09-29T00:00:00.000Z"}]}})
        time.sleep(0.3)
        tab_complete(13, "https://www.sncf-connect.com/")
        time.sleep(0.8)
        st = pstate(s)
        check("notify: no notification when no voucher is valid",
              len(st["notifications"]) == 2, st["notifications"])

        # ---- expiry lead-time notification (background/expiry-notify.js;
        # the shim has an alarms mock, the check is driven by the storage
        # change events the script itself listens to) ----
        def notifs_for(code):
            st = pstate(s)
            return [n for n in st["notifications"] if code in n["message"]]

        def settings_items(**kw):
            base = {"theme": "system", "language": "system", "notifications": True}
            base.update(kw)
            return {"settings": base}

        soon3_d = (date.today() + timedelta(days=3)).isoformat()
        soon2_d = (date.today() + timedelta(days=2)).isoformat()
        today_d = date.today().isoformat()
        expiry_vouchers = [
            {"id": "seed-e-1", "code": "E2E-EXPSOON-1",
             "expiryDate": soon3_d, "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-e-2", "code": "E2E-EXPTODAY-1",
             "expiryDate": today_d, "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-e-3", "code": "E2E-EXPFAR-1",
             "expiryDate": "2028-06-30", "createdAt": "2026-09-29T00:00:00.000Z"},
            {"id": "seed-e-4", "code": "E2E-OLDEXP-9",
             "expiryDate": "2020-01-01", "createdAt": "2026-09-29T00:00:00.000Z"}]

        page_cmd({"op": "local-set", "items": {"vouchers": expiry_vouchers}})
        time.sleep(0.8)
        check("expiry: vouchers inside the lead window notify, today included",
              len(notifs_for("E2E-EXPSOON-1")) == 1
              and len(notifs_for("E2E-EXPTODAY-1")) == 1
              and "expires today" in notifs_for("E2E-EXPTODAY-1")[0]["message"]
              and "(in 3 days)" in notifs_for("E2E-EXPSOON-1")[0]["message"]
              and len(notifs_for("E2E-EXPFAR-1")) == 0,
              pstate(s)["notifications"])

        page_cmd({"op": "local-set", "items": {"vouchers": expiry_vouchers}})
        time.sleep(0.8)
        check("expiry: the same voucher never notifies twice",
              len(notifs_for("E2E-EXPSOON-1")) == 1
              and len(notifs_for("E2E-EXPTODAY-1")) == 1,
              pstate(s)["notifications"])

        # lead time 1 day: a voucher expiring in 2 days stays silent
        page_cmd({"op": "local-set",
                  "items": settings_items(notifyLeadDays=1)})
        page_cmd({"op": "local-set", "items": {"vouchers":
                    expiry_vouchers + [
                        {"id": "seed-e-5", "code": "E2E-EXPLEAD-1",
                         "expiryDate": soon2_d,
                         "createdAt": "2026-09-29T00:00:00.000Z"}]}})
        time.sleep(0.8)
        check("expiry: a lead time of 1 day skips a voucher expiring in 2 days",
              len(notifs_for("E2E-EXPLEAD-1")) == 0,
              pstate(s)["notifications"])

        # raising the lead time back to 7 notifies the pending voucher
        page_cmd({"op": "local-set",
                  "items": settings_items(notifyLeadDays=7)})
        time.sleep(0.8)
        check("expiry: raising the lead time notifies the pending voucher",
              len(notifs_for("E2E-EXPLEAD-1")) == 1,
              pstate(s)["notifications"])

        # the notifications toggle gates the expiry reminder too
        page_cmd({"op": "local-set",
                  "items": settings_items(notifications=False)})
        page_cmd({"op": "local-set", "items": {"vouchers":
                    expiry_vouchers + [
                        {"id": "seed-e-6", "code": "E2E-EXPOFF-1",
                         "expiryDate": today_d,
                         "createdAt": "2026-09-29T00:00:00.000Z"}]}})
        time.sleep(0.8)
        check("expiry: the settings toggle turns the expiry reminder off",
              len(notifs_for("E2E-EXPOFF-1")) == 0,
              pstate(s)["notifications"])

        # the dedicated expiry-reminders checkbox gates only the expiry
        # notification (the master toggle is back on)
        page_cmd({"op": "local-set",
                  "items": settings_items(expiryNotifications=False)})
        page_cmd({"op": "local-set", "items": {"vouchers":
                    expiry_vouchers + [
                        {"id": "seed-e-7", "code": "E2E-EXPEXPOFF-1",
                         "expiryDate": today_d,
                         "createdAt": "2026-09-29T00:00:00.000Z"}]}})
        time.sleep(0.8)
        check("expiry: the expiry-reminders checkbox silences the expiry notification",
              len(notifs_for("E2E-EXPEXPOFF-1")) == 0,
              pstate(s)["notifications"])
        page_cmd({"op": "local-set",
                  "items": settings_items(expiryNotifications=True)})
        time.sleep(0.8)
        check("expiry: re-checking the checkbox notifies the pending voucher",
              len(notifs_for("E2E-EXPEXPOFF-1")) == 1,
              pstate(s)["notifications"])

        # ---- snooze: click the notification -> silent until the next day
        st = pstate(s)
        exp_notif = [n for n in st["notifications"]
                     if "E2E-EXPEXPOFF-1" in n["message"]][-1]
        check("expiry: notification carries its voucher id, hint, no buttons (Firefox surface)",
              exp_notif["id"] == "wagonbar-exp-seed-e-7"
              and exp_notif["buttons"] is None
              and "Click to be reminded tomorrow" in exp_notif["message"],
              exp_notif)

        page_cmd({"op": "notif-click", "id": "wagonbar-exp-seed-e-7"})
        time.sleep(0.5)
        st = pstate(s)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        check("expiry: clicking the notification snoozes it until tomorrow",
              st["expSnooze"].get("seed-e-7") == tomorrow
              and "seed-e-7" not in st["expNotified"],
              (st["expSnooze"], st["expNotified"]))

        # a check while snoozed stays silent
        page_cmd({"op": "local-set", "items": settings_items()})
        time.sleep(0.8)
        check("expiry: a snoozed voucher does not notify again",
              len(notifs_for("E2E-EXPEXPOFF-1")) == 1,
              pstate(s)["notifications"])

        # time travel: the snooze date has passed -> the voucher notifies
        page_cmd({"op": "local-set", "items": dict(
            settings_items(),
            expirySnooze={"seed-e-7": (date.today() - timedelta(days=1)).isoformat()})})
        time.sleep(0.8)
        st = pstate(s)
        check("expiry: after the snooze date the voucher notifies again",
              len(notifs_for("E2E-EXPEXPOFF-1")) == 2
              and "seed-e-7" not in st["expSnooze"],
              (st["notifications"], st["expSnooze"]))

        # ---- voucher value in euros (optional field) ----
        s.client.navigate(url)
        time.sleep(1)

        popup_add(s, "E2E-VAL-1", "2026-11-11", "25")
        time.sleep(0.6)
        st = pstate(s)
        rec = next(v for v in st["store"] if v["code"] == "E2E-VAL-1")
        check("value: new voucher stores the euro amount and shows it",
              rec.get("amount") == 25 and len(st["items"]) == 1
              and "25 \u20ac" in st["items"][0]["text"],
              (rec, st["items"][0]["text"]))

        popup_add(s, "E2E-NOVAL-1", "2026-11-12")
        time.sleep(0.6)
        st = pstate(s)
        rec = next(v for v in st["store"] if v["code"] == "E2E-NOVAL-1")
        check("value: the amount stays optional (no key when empty)",
              "amount" not in rec
              and "\u20ac" not in st["items"][1]["text"],
              (rec, st["items"][1]["text"]))

        popup_add(s, "E2E-BADVAL-1", "2026-11-13", "abc")
        time.sleep(0.6)
        st = pstate(s)
        check("value: an invalid amount is rejected inline, nothing added",
              len(st["items"]) == 2 and not st["status"]["hidden"]
              and "value in euros" in st["status"]["text"], st["status"])

        # editing loads the amount and can change (or clear) it
        s.page_js("document.querySelector('.voucher-item .edit-btn').click();"
                  "return 'ok';")
        time.sleep(0.4)
        check("popup: clicking Edit opens the collapsed add form",
              s.page_js(
                  "return document.getElementById('addVoucherForm').hidden;") is False)
        loaded = s.page_js("return document.getElementById('voucherValue').value;")
        s.page_js("document.getElementById('voucherValue').value = '30,5';"
                  "document.getElementById('addVoucherForm').dispatchEvent("
                  "  new Event('submit', {bubbles: true, cancelable: true}));"
                  "return 'ok';")
        time.sleep(0.6)
        st = pstate(s)
        rec = next(v for v in st["store"] if v["code"] == "E2E-VAL-1")
        check("value: edit loads the amount, comma decimals accepted",
              loaded == "25" and rec.get("amount") == 30.5,
              (loaded, rec))
        check("popup: add form collapses again after a successful update",
              s.page_js(
                  "return document.getElementById('addVoucherForm').hidden;") is True)

        # stats show the summed value of the valid vouchers
        st = pstate(s)
        check("value: stats sum the valid vouchers' amounts",
              st["total"] == "2" and st["valid"] == "2"
              and st["value"] == "30.5", (st["total"], st["valid"], st["value"]))

        # sort by value: highest first, no-amount vouchers last
        popup_add(s, "E2E-VAL-2", "2027-01-01", "50")
        time.sleep(0.6)
        s.page_js("var s = document.getElementById('sortOrder');"
                  "s.value = 'value'; s.dispatchEvent(new Event('change'));"
                  "return 'ok';")
        time.sleep(0.5)
        st = pstate(s)
        # voucher codes never contain spaces; the item text also carries
        # the amount and expiry lines, so take the first token
        codes = [i["text"].split(" ")[0] for i in st["items"]]
        check("value: sort by value puts the highest first, no-amount last",
              codes == ["E2E-VAL-2", "E2E-VAL-1", "E2E-NOVAL-1"]
              and st["value"] == "80.5", (codes, st["value"]))

        # ---- draft: the popup is destroyed when it loses focus; a
        # half-filled form survives as a storage.local draft ----
        s.client.navigate(url + "?e2e-draft=" + quote(json.dumps(
            {"code": "DRAFTTEST1", "value": "25", "date": "2027-02-02",
             "open": True})))
        time.sleep(1)
        draft_st = json.loads(s.page_js(
            "return JSON.stringify({"
            " hidden: document.getElementById('addVoucherForm').hidden,"
            " code: document.getElementById('voucherCode').value,"
            " value: document.getElementById('voucherValue').value,"
            " date: document.getElementById('expiryDate').value,"
            " submit: document.getElementById('submitBtn').textContent,"
            " cancelHidden: document.getElementById('cancelEditBtn').hidden});"))
        check("draft: a saved draft reopens the form with its fields",
              draft_st["hidden"] is False
              and draft_st["code"] == "DRAFTTEST1"
              and draft_st["value"] == "25"
              and draft_st["date"] == "2027-02-02"
              and draft_st["submit"] == "Add Voucher",
              draft_st)

        # an editing draft restores edit mode when the voucher exists
        s.client.navigate(url + "?e2e-seed=" + quote(json.dumps(
            [{"id": "draft-e-1", "code": "DRAFTEDIT1",
              "expiryDate": "2027-03-03",
              "createdAt": "2026-09-29T00:00:00.000Z"}]))
            + "&e2e-draft=" + quote(json.dumps(
                {"code": "DRAFTEDIT1", "value": "", "date": "2027-04-04",
                 "editingId": "draft-e-1"})))
        time.sleep(1)
        draft_st = json.loads(s.page_js(
            "return JSON.stringify({"
            " hidden: document.getElementById('addVoucherForm').hidden,"
            " date: document.getElementById('expiryDate').value,"
            " submit: document.getElementById('submitBtn').textContent,"
            " cancelHidden: document.getElementById('cancelEditBtn').hidden});"))
        check("draft: an editing draft restores update mode",
              draft_st["hidden"] is False
              and draft_st["date"] == "2027-04-04"
              and draft_st["submit"] == "Update Voucher"
              and draft_st["cancelHidden"] is False,
              draft_st)

        # typing saves the draft; submitting (add or update) clears it
        s.page_js("var c = document.getElementById('voucherCode');"
                  "c.value = 'DRAFTNEW-1';"
                  "c.dispatchEvent(new Event('input')); return 'ok';")
        time.sleep(0.4)
        st = pstate(s)
        check("draft: typing persists the draft",
              (st["draft"] or {}).get("code") == "DRAFTNEW-1", st["draft"])
        popup_add(s, "DRAFTNEW-1", "2027-05-05")
        time.sleep(0.6)
        st = pstate(s)
        check("draft: a successful submit clears the draft",
              st["draft"] is None
              and any(v["code"] == "DRAFTNEW-1" for v in st["store"]),
              (st["draft"], st["store"]))

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


if __name__ == "__main__":
    sys.exit(main())
