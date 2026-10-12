"""End-to-end tests for the SNCF Voucher Reminder Firefox extension.

Drives a real headless Firefox via Marionette, installs the extension as a
temporary add-on, and verifies the full stack: manifest load, popup logic
(real popup.js against a mocked browser.storage), storage backend, and the
toolbar icon badge showing the number of valid vouchers.

Usage:
    python tests/e2e/wagonbar_e2e.py a    # install + empty badge + popup logic
    python tests/e2e/wagonbar_e2e.py b    # seeded storage + badge count

Requires:
    - Firefox 121+ (Manifest V3 background event page) reachable as
      ``firefox.exe`` on PATH or by full path via the FIREFOX_BIN env var
    - ``pip install marionette_driver``
    - pwsh (PowerShell 7) for orphan-process cleanup on Windows

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
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import date, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

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
  var store = {vouchers: []};
  var alerts = [];
  var confirms = [];
  function sync(){
    root.setAttribute('data-e2e-store', JSON.stringify(store.vouchers));
    root.setAttribute('data-e2e-alerts', JSON.stringify(alerts));
    root.setAttribute('data-e2e-confirms', JSON.stringify(confirms));
  }
  window.alert = function(m){ alerts.push(String(m)); sync(); };
  window.confirm = function(){ confirms.push('called'); sync(); return true; };
  window.browser = {storage: {local: {
    get: function(k){ return Promise.resolve(JSON.parse(JSON.stringify(store))); },
    set: function(obj){ Object.assign(store, JSON.parse(JSON.stringify(obj)));
                        sync(); return Promise.resolve(); }
  }}};
  sync();
})();
"""


def build_popup_test_page(port):
    d = tempfile.mkdtemp(prefix="wagonbar-popup-test-")
    for f in ("popup.css", "popup.js"):
        shutil.copy(os.path.join(POPUP_DIR, f), os.path.join(d, f))
    html = open(os.path.join(POPUP_DIR, "popup.html"), encoding="utf-8").read()
    shim_tag = "<script>%s</script>" % SHIM
    html = html.replace("<script src=\"popup.js\"></script>",
                        shim_tag + "\n  <script src=\"popup.js\"></script>")
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
        " store: JSON.parse(document.documentElement.getAttribute('data-e2e-store') || '[]')"
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

        soon = date.today() + timedelta(days=7)
        soon_d = soon.strftime("%Y-%m-%d")
        popup_add(s, "E2E-FUTURE-999", "2028-06-30")
        popup_add(s, "E2E-SOON-111", soon_d)
        popup_add(s, "E2E-EXPIRED-1", "2020-01-01")
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

        # date entry: digits are auto-dashed and the remaining format is
        # kept visible as a grey hint behind the typed text
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
        check("popup: partial date keeps grey hint of remaining format",
              st["value"] == "2026" and st["ghostRest"] == "-MM-DD", st)

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

        # odd-length code: saved anyway, but a warning is displayed
        popup_add(s, "SHORT", "2027-03-03")
        time.sleep(0.6)
        st = pstate(s)
        check("popup: odd-length code saved with warning, not blocked",
              any(v["code"] == "SHORT" for v in st["store"])
              and not st["status"]["hidden"]
              and "usual" in st["status"]["text"],
              (st["status"], st["store"]))
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
    ]
    s = Session(seed_vouchers=vouchers)
    try:
        check("extension installs (phase B)", s.addon_id == ADDON_ID, s.addon_id)
        check("badge: shows count of valid vouchers (expired one filtered out)",
              wait_for_badge(s, "2"), badge_text(s))
    finally:
        s.close()


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "a"
    if phase == "a":
        phase_a()
    elif phase == "b":
        phase_b()
    else:
        print("usage: wagonbar_e2e.py [a|b]")
        return 2
    failed = [n for n, ok in RESULTS if not ok]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)), flush=True)
    for n in failed:
        print("FAILED: " + n, flush=True)
    return 1 if failed else 0


sys.exit(main())
