# Tests

## e2e

`e2e/wagonbar_e2e.py` drives a real headless Firefox (via Marionette, which is
built into Firefox) with the extension installed as a temporary add-on, in
disposable profiles.

Prerequisites:

- Firefox 121+ available as `firefox.exe` on PATH (or set `FIREFOX_BIN` to the
  executable)
- `pip install marionette_driver`
- pwsh for cleanup on Windows

Run both phases (each launches and tears down its own Firefox instance):

```bash
python tests/e2e/wagonbar_e2e.py a   # install + empty badge + popup logic
python tests/e2e/wagonbar_e2e.py b   # seeded storage + badge count
```

The phases are separate because the storage backend caches its data file after
the first read: phase B seeds `browser.storage.local` before the extension's
first storage access and therefore needs a fresh session.

What is covered:

- MV3 manifest accepted and add-on installed
- popup.js logic end to end (add, sort, duplicate, inline error status,
  two-step delete, counts, expired/valid classes, date rendering) — in a
  localhost-served copy of popup.html with a mocked `browser.storage`
  (Firefox blocks automation of real extension pages); asserts that no
  native `alert`/`confirm` dialogs are used. Also covers the custom date
  entry: typed YYYY-MM-DD dates, impossible dates (Feb 31) rejected
  inline, dates in the past rejected inline (today is the earliest
  allowed), dashes auto-inserted while typing with the remaining format
  shown as a grey hint, and the calendar widget (opens on the icon,
  past days disabled, today selectable, picking a day fills the field
  and closes). Expired vouchers can no longer be created through the
  form, so expired rendering is covered with storage seeded directly
  (legacy data)
- voucher codes: pasted spaces/newlines trimmed, usual-length codes saved
  without warning, odd-length codes warn (without blocking) as soon as
  focus leaves the code field
- editing: "Edit" loads a voucher into the form (submit relabeled,
  Cancel appears), saving updates it in place (unchanged code not treated
  as a duplicate) with a success message, Cancel exits without changes
- sorting: by expiration date by default, switchable to by code, kept
  across renders
- status messages: warnings dismissible by click and auto-expiring;
  errors stay until the next action
- toolbar badge on the extension icon: empty with no vouchers, and the count
  of valid vouchers with seeded storage (expired filtered out, expiring-today
  kept) — read from the toolbar button in chrome context; the button is pinned
  to the nav-bar via a seeded `browser.uiCustomization.state` because a fresh
  profile parks extension buttons in the lazily-built unified-extensions panel
- same-day expiry: a voucher expiring today counts as valid through the end
  of its expiry day in both the popup and the badge (guards against parsing
  date-only strings as UTC)

Not covered: the toolbar popup panel itself (not automatable), badge
colors (not exposed as DOM attributes).
