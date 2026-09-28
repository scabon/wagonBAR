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
python tests/e2e/wagonbar_e2e.py a   # install + no-voucher banner + popup logic
python tests/e2e/wagonbar_e2e.py b   # seeded storage + banner + close button
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
  native `alert`/`confirm` dialogs are used
- content script on the real https://www.sncf-connect.com/: no banner with no
  vouchers, banner showing the oldest valid voucher (expired filtered out)
  with correct count and date, close button, and "Manage Vouchers" opening
  the manage page in a new tab

Not covered: the toolbar popup panel itself (not automatable), the booking-page
"Copy Code" banner variant (no stable booking URL), clipboard writes.
