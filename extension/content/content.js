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
    return hostname === 'sncf-connect.com' ||
           hostname === 'www.sncf-connect.com';
  } catch (e) {
    return false;
  }
}

// Create an element with optional class and text
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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

  // Check if we're on a page where vouchers can be used (booking page)
  const isBookingPage = isBookingPageUrl();

  // Create reminder banner
  const banner = el('div');
  banner.id = 'sncf-voucher-reminder';
  banner.className = 'sncf-voucher-banner';

  const content = el('div', 'banner-content');
  content.appendChild(el('div', 'banner-icon', '🎫'));

  const text = el('div', 'banner-text');
  text.appendChild(el('strong', null,
    `You have ${voucherCount} valid SNCF voucher${voucherCount > 1 ? 's' : ''}!`));

  const oldestLine = el('p');
  oldestLine.appendChild(document.createTextNode('Oldest: '));
  const codeNode = el('code', null, oldestVoucher.code);
  oldestLine.appendChild(codeNode);
  if (isBookingPage) {
    oldestLine.appendChild(document.createTextNode(
      ` (expires ${expiryDateStr}, ${daysLeft} day${daysLeft !== 1 ? 's' : ''} left)`));
  } else {
    oldestLine.appendChild(document.createTextNode(` (expires ${expiryDateStr})`));
  }
  text.appendChild(oldestLine);

  if (isBookingPage) {
    text.appendChild(el('p', 'banner-hint', "Don't forget to apply it before paying!"));
  }

  content.appendChild(text);

  const closeBtn = el('button', 'banner-close', '×');
  closeBtn.title = 'Close';
  content.appendChild(closeBtn);

  banner.appendChild(content);

  const footer = el('div', 'banner-footer');
  if (isBookingPage) {
    const copyBtn = el('button', 'banner-btn copy-btn', 'Copy Code');
    copyBtn.setAttribute('data-code', oldestVoucher.code);
    footer.appendChild(copyBtn);
  }
  footer.appendChild(el('button', 'banner-btn manage-btn', 'Manage Vouchers'));
  banner.appendChild(footer);

  // Style the banner - check for dark mode preference
  const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const bannerGradient = isDarkMode
    ? 'linear-gradient(135deg, #004488, #003366)'
    : 'linear-gradient(135deg, #0066cc, #0052a3)';

  banner.style.cssText = `
    position: fixed;
    bottom: 20px;
    right: 20px;
    max-width: 400px;
    background: ${bannerGradient};
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
  closeBtn.addEventListener('click', function() {
    banner.remove();
  });

  const copyBtn = banner.querySelector('.copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function() {
      const code = copyBtn.getAttribute('data-code');
      copyToClipboard(code);
      // Show feedback
      const originalText = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      setTimeout(() => {
        copyBtn.textContent = originalText;
      }, 2000);
    });
  }

  banner.querySelector('.manage-btn').addEventListener('click', function() {
    // Open the manage page in a new tab
    browser.runtime.sendMessage({ action: 'openPopup' });
    banner.remove();
  });

  // Dim after 20 seconds if not interacted with
  setTimeout(() => {
    if (banner.parentNode) {
      banner.style.opacity = '0.8';
    }
  }, 20000);

  // Auto-close after 30 seconds
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
