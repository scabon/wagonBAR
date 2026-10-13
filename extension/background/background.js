// Background script for SNCF Voucher Reminder
// Handles storage and keeps the toolbar badge in sync with valid vouchers

// Get all valid vouchers
function getValidVouchers() {
  return browser.storage.local.get('vouchers').then(function(data) {
    const vouchers = data.vouchers || [];
    const now = new Date();
    now.setHours(0, 0, 0, 0);

    return vouchers.filter(v => {
      // Parse as local midnight (a date-only string would be read as UTC
      // and a voucher expiring today could look already expired)
      const expiryDate = new Date(v.expiryDate + 'T00:00:00');
      return expiryDate >= now;
    }).sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
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
