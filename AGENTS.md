# AGENTS.md — wagonBAR

SNCF Connect voucher-reminder browser extension (Manifest V3), source in
`extension/`. Not affiliated with SNCF.

## Core rules

1. **Privacy stance**: no content scripts, no host permissions, no
   analytics, no third-party backend. The `tabs` permission is only used
   to read tab URLs for the sncf-connect.com arrival notification.
2. **Cross-browser is a standing requirement**: Firefox (shipped target),
   Chrome/Chromium, and Safari code-compatible, from a single source tree.
   The promise-based `browser.*` namespace (vendored webextension-polyfill)
   covers Chromium; toolbar icons are PNG because Chrome cannot render SVG.
3. **Sync architecture**: `storage.local` is the durable source of truth;
   `storage.sync` is only a replication copy. One sync key per voucher
   (`voucher-<id>`); deletes are tombstones; per-voucher last-write-wins by
   `updatedAt`. Do not add a local-onChanged to sync mirror in the
   background (change-event echo races the merge).
4. **i18n**: en + fr, every user-facing string in both languages (the
   STRINGS dict in `extension/popup/popup.js`).
5. **Changelog**: CHANGELOG.md is the source of truth; the English
   `changelogEntries` in `extension/popup/popup.js` must mirror it exactly
   (checked by the release tooling) and the latest section must match the
   manifest version.
6. **e2e**: `python tests/e2e/wagonbar_e2e.py a|b|c` must stay green
   (a/b: Firefox Marionette; c: Chromium load smoke). Add-on ID
   `wagonbar@scabon.com` (unchangeable after first publication).

## Build & test

- Lint: `npx web-ext lint --source-dir extension`
- Firefox package: `npx web-ext build --source-dir extension --artifacts-dir dist`
- The Chromium MV3 package and the store release/upload tooling are
  maintained privately by the author.
