// Content script for SNCF Voucher Reminder
// Shows reminders when on SNCF Connect website

console.log('SNCF Voucher Reminder content script loaded');

// Check if we're on SNCF Connect and show reminder
function checkAndShowReminder() {
  // Check if this is SNCF Connect
  if (!isSNCFConnectPage()) {
    return;
  }
  
  // Ask background script for valid vouchers
  browser.runtime.sendMessage({ action: 'getValidVouchers' }).then(function(response) {
    if (response && response.vouchers && response.vouchers.length > 0) {
      showVoucherReminder(response.vouchers);
    }
  }).catch(function(error) {
    console.log('Error checking vouchers:', error);
  });
}

// Check if current page is SNCF Connect
function isSNCFConnectPage() {
  try {
    const hostname = window.location.hostname;
    return hostname.includes('sncf-connect.com') || 
           hostname.includes('www.sncf-connect.com');
  } catch (e) {
    return false;
  }
}

// Show voucher reminder banner
function showVoucherReminder(vouchers) {
  // Don't show if already shown
  if (document.getElementById('sncf-voucher-reminder')) {
    return;
  }
  
  // Get the oldest voucher (first in sorted list)
  const oldestVoucher = vouchers[0];
  const voucherCount = vouchers.length;
  
  // Format expiry date
  const expiryDate = new Date(oldestVoucher.expiryDate);
  const daysLeft = Math.ceil((expiryDate - new Date()) / (1000 * 60 * 60 * 24));
  const expiryDateStr = formatDate(expiryDate);
  
  // Create reminder banner
  const banner = document.createElement('div');
  banner.id = 'sncf-voucher-reminder';
  banner.className = 'sncf-voucher-banner';
  
  // Check if we're on a page where vouchers can be used (booking page)
  const isBookingPage = isBookingPageUrl();
  
  if (isBookingPage) {
    // On booking page - suggest using the voucher
    banner.innerHTML = `
      <div class="banner-content">
        <div class="banner-icon">🎫</div>
        <div class="banner-text">
          <strong>You have ${voucherCount} valid SNCF voucher${voucherCount > 1 ? 's' : ''}!</strong>
          <p>Oldest: <code>${oldestVoucher.code}</code> (expires ${expiryDateStr}, ${daysLeft} day${daysLeft !== 1 ? 's' : ''} left)</p>
          <p class="banner-hint">Don't forget to apply it before paying!</p>
        </div>
        <button class="banner-close" title="Close">×</button>
      </div>
      <div class="banner-footer">
        <button class="banner-btn copy-btn" data-code="${oldestVoucher.code}">Copy Code</button>
        <button class="banner-btn manage-btn">Manage Vouchers</button>
      </div>
    `;
  } else {
    // On other pages - just remind
    banner.innerHTML = `
      <div class="banner-content">
        <div class="banner-icon">🎫</div>
        <div class="banner-text">
          <strong>You have ${voucherCount} valid SNCF voucher${voucherCount > 1 ? 's' : ''}!</strong>
          <p>Oldest: <code>${oldestVoucher.code}</code> (expires ${expiryDateStr})</p>
        </div>
        <button class="banner-close" title="Close">×</button>
      </div>
      <div class="banner-footer">
        <button class="banner-btn manage-btn">Manage Vouchers</button>
      </div>
    `;
  }
  
  // Style the banner
  banner.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    max-width: 400px;
    background: linear-gradient(135deg, #0066cc, #0052a3);
    color: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    z-index: 999999;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px;
    overflow: hidden;
  `;
  
  // Add to body
  document.body.appendChild(banner);
  
  // Add event listeners
  const closeBtn = banner.querySelector('.banner-close');
  const copyBtn = banner.querySelector('.copy-btn');
  const manageBtn = banner.querySelector('.manage-btn');
  
  closeBtn.addEventListener('click', function() {
    banner.remove();
  });
  
  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      const code = this.getAttribute('data-code');
      copyToClipboard(code);
      // Show feedback
      const originalText = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      setTimeout(() => {
        copyBtn.textContent = originalText;
      }, 2000);
    });
  }
  
  manageBtn.addEventListener('click', function() {
    // Open the extension popup
    browser.runtime.sendMessage({ action: 'openPopup' });
    banner.remove();
  });
  
  // Auto-close after 30 seconds if not interacted with
  setTimeout(() => {
    if (banner.parentNode) {
      banner.style.opacity = '0.8';
    }
  }, 20000);
  
  setTimeout(() => {
    if (banner.parentNode) {
      banner.remove();
    }
  }, 30000);
}

// Check if current URL is a booking page
function isBookingPageUrl() {
  const path = window.location.pathname;
  const bookingPaths = [
    '/booking',
    '/reservation',
    '/panier',
    '/cart',
    '/checkout',
    '/paiement',
    '/payment'
  ];
  
  return bookingPaths.some(p => path.toLowerCase().includes(p));
}

// Copy text to clipboard
function copyToClipboard(text) {
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  
  try {
    document.execCommand('copy');
  } catch (e) {
    // Fallback for modern browsers
    navigator.clipboard.writeText(text).catch(() => {});
  }
  
  document.body.removeChild(textarea);
}

// Format date as DD/MM/YYYY
function formatDate(date) {
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}/${month}/${year}`;
}

// Listen for messages from background script
browser.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.action === 'showReminder') {
    showVoucherReminder(request.vouchers);
  }
});

// Check periodically if we should show reminder
// (in case content script loads before page is ready)
let checkInterval = setInterval(function() {
  if (document.readyState === 'complete') {
    checkAndShowReminder();
    clearInterval(checkInterval);
  }
}, 500);

// Also check on page load
if (document.readyState === 'complete') {
  checkAndShowReminder();
} else {
  window.addEventListener('load', checkAndShowReminder);
}
