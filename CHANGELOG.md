# Changelog

All notable changes to wagonBar are documented here. This file is the
source of truth for the popup's Changelog view: the English entries in
`extension/popup/popup.js` must match it exactly (checked by
`tools/check-changelog.py`, run in CI), and the French entries are a
manual translation of the same items.

When releasing a new version:

1. add a `## [<version>] — <date>` section here, newest first;
2. mirror the same items into the English `changelogEntries` in
   `extension/popup/popup.js` and translate them into the French block;
3. bump `"version"` in `extension/manifest.json` to match the new section;
4. run `python tools/check-changelog.py`.

## [1.7.1] — 2026-11-01

- Export your vouchers to a JSON file (backup) and import them back — Settings → Export / Import. Exports carry the SNCF Connect site, so they also import as-is into bandWagon.
- Fixed: the import file picker did not open on Firefox (hidden file input; now rendered off-screen).

## [1.7] — 2026-10-27

- New Changelog view in the popup menu, listing the changes of every release.
- The popup title no longer runs under the menu button.

## [1.6] — 2026-10-26

- Runs on Firefox for Android, with a touch-friendly full-width popup.
- Disabled calendar days are clearly dimmed.

## [1.5] — 2026-10-25

- New wagonBar icons.
- Notification when you open SNCF Connect with a valid voucher, showing the days left.
- Expiry reminders: configurable lead time, richer actions and a "Remind me tomorrow" snooze.
- Fixed expiry notifications never firing on Firefox.
- Optional voucher value in euros, with a total and a sort-by-value option.
- One-click SNCF Connect link above the list, shown only when a voucher is usable.
- The add form collapses behind a + button and a half-filled form is kept when the popup reopens.

## [1.4] — 2026-10-13

- Vouchers sync across devices through your browser account.
- Runs on Chrome/Chromium-based browsers.
- Expiry reminder lead time setting, list sorting, past dates rejected.

## [1.3] — 2026-10-12

- Voucher management moved into the popup (no more content scripts).
- ISO date entry with auto-dashes, dark theme, edit and delete, remove expired.

## [1.0 – 1.2] — 2026-05-06

- First releases: SNCF voucher reminders with expiry notifications.
