// Background script for SNCF Voucher Reminder
// Handles storage and keeps the toolbar badge in sync with valid vouchers

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

// Update the toolbar icon badge with the number of valid vouchers
function updateBadge() {
  return getValidVouchers().then(function(vouchers) {
    const text = vouchers.length > 0 ? String(vouchers.length) : '';
    return browser.action.setBadgeText({ text: text }).then(function() {
      return browser.action.setBadgeBackgroundColor({ color: '#0066cc' });
    }).then(function() {
      return browser.action.setBadgeTextColor({ color: '#ffffff' });
    });
  }).catch(function(e) {
    console.log('Could not update badge:', e);
  });
}

// Update the badge whenever the voucher list changes
browser.storage.onChanged.addListener(function(changes, area) {
  if (area === 'local' && changes.vouchers) {
    updateBadge();
  }
});

// Set the badge once the event page starts (install and browser startup)
updateBadge();
