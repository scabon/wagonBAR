Vendored copies of third-party libraries.

## browser-polyfill.js

Mozilla's [webextension-polyfill](https://github.com/mozilla/webextension-polyfill)
v0.12.0, downloaded from
<https://unpkg.com/webextension-polyfill/dist/browser-polyfill.js>
(MPL-2.0; the license header is in the file).

It provides the promise-based `browser.*` namespace on Chrome/Chromium.
In Firefox and Safari the native `browser` global already exists and the
polyfill is a no-op.
