// Background script for SNCF Voucher Reminder
// Handles storage and provides helper functions

// Get the oldest valid voucher
function getOldestValidVoucher() {
  return browser.storage.local.get('vouchers').then(function(data) {
    const vouchers = data.vouchers || [];
    const now = new Date();
    now.setHours(0, 0, 0, 0);

    // Filter valid vouchers and sort by expiry date (oldest first)
    const validVouchers = vouchers.filter(v => {
      const expiryDate = new Date(v.expiryDate);
      return expiryDate >= now;
    }).sort((a, b) => new Date(a.expiryDate) - new Date(b.expiryDate));

    return validVouchers.length > 0 ? validVouchers[0] : null;
  });
}

// Get all valid vouchers
function getValidVouchers() {
  return browser.storage.local.get('vouchers').then(function(data) {
    const vouchers = data.vouchers || [];
    const now = new Date();
    now.setHours(0, 0, 0, 0);

    return vouchers.filter(v => {
      const expiryDate = new Date(v.expiryDate);
      return expiryDate >= now;
    }).sort((a, b) => new Date(a.expiryDate) - new Date(b.expiryDate));
  });
}

// Check if current tab is SNCF Connect
function isSNCFConnectTab(tab) {
  if (!tab || !tab.url) return false;

  try {
    const url = new URL(tab.url);
    return url.hostname === 'sncf-connect.com' ||
           url.hostname === 'www.sncf-connect.com';
  } catch (e) {
    return false;
  }
}

// Listen for messages from content script
browser.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.action === 'getOldestValidVoucher') {
    getOldestValidVoucher().then(function(voucher) {
      sendResponse({ voucher: voucher });
    });
    return true; // Required for async response
  }

  if (request.action === 'getValidVouchers') {
    getValidVouchers().then(function(vouchers) {
      sendResponse({ vouchers: vouchers });
    });
    return true;
  }

  if (request.action === 'openPopup') {
    browser.action.openPopup().catch(function(e) {
      // openPopup can fail (e.g. without user interaction); ignore
      console.log('Could not open popup:', e);
    });
  }
});

// Check on tab update if it's SNCF Connect
// This triggers a reminder banner for already-loaded tabs
browser.tabs.onUpdated.addListener(function(tabId, changeInfo, tab) {
  if (changeInfo.status === 'complete' && isSNCFConnectTab(tab)) {
    // Check if we should show a reminder
    getValidVouchers().then(function(vouchers) {
      if (vouchers && vouchers.length > 0) {
        // Send message to content script to show reminder
        browser.tabs.sendMessage(tabId, {
          action: 'showReminder',
          vouchers: vouchers
        }).catch(() => {
          // Content script might not be injected yet, that's ok
        });
      }
    });
  }
});
