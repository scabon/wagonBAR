// Chrome/Chromium (Manifest V3) background entry point. Firefox uses
// background.scripts and never loads this file; Chrome requires a service
// worker, which imports the browser.* polyfill first and then the shared
// background logic (unchanged for both engines).
importScripts('/vendor/browser-polyfill.js', '/background/background.js');
