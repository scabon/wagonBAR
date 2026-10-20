// Chrome/Chromium (Manifest V3) background entry point. Firefox uses
// background.scripts and never loads this file; Chrome requires a service
// worker, which imports the browser.* polyfill first and then the shared
// background and sync logic (unchanged for both engines).
importScripts('/vendor/browser-polyfill.js', '/shared/sync-common.js',
              '/background/background.js', '/background/sync.js',
              '/background/sncf-notify.js', '/background/expiry-notify.js');
