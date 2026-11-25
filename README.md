# wagonBAR

Browser extension to help you manage and remember to use your SNCF Connect
vouchers (bons d'achat). Not affiliated with SNCF.

Firefox is the shipped target; Chrome/Chromium-based browsers are supported
too, and Safari stays code-compatible.

## Features

- Add vouchers with codes and expiration dates
- View all vouchers sorted by expiration (oldest first), color-coded
- Toolbar badge shows the number of valid vouchers
- Delete used or expired vouchers
- Export/import vouchers as JSON (backup) from Settings — exports also import into bandWagon
- Cross-device sync through your own browser account — no third-party server
- Expiry lead-time reminders and a notification when you open sncf-connect.com
- Light/dark theme, English and French, desktop and Firefox for Android

## Privacy

No account, no analytics, no tracking, no third-party server. No content
scripts and no host permissions: the `tabs` permission is only used to read
tab URLs for the sncf-connect.com arrival notification. Vouchers are typed in
by you, nothing is scraped. Data lives in `storage.local` and replicates only
through your own browser account's sync.

## Installation

- **Firefox** — [addons.mozilla.org](https://addons.mozilla.org/addon/wagonbar/)
- **Chrome** — [Chrome Web Store](https://chromewebstore.google.com/detail/wagonbar/ccfbilijaieheadekfokopnjomleneka)
- **Edge** — [Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/kbjkmnahogbpfipgfbdimnmpfcbdpgbh)
- **From source** — see [extension/README.md](extension/README.md) (temporary add-on in `about:debugging`, or `npx web-ext build --source-dir extension`)

## Project layout

- `extension/` — all extension code ([extension/README.md](extension/README.md))
- `tests/` — the Marionette e2e suite, phases a/b/c (see `tests/README.md`)

Store-listing assets and the release/upload tooling are maintained privately
by the author.

Add-on ID: `wagonbar@scabon.com`.

## License

MIT — see [LICENSE](LICENSE).
