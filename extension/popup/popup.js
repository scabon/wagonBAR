// Popup script for SNCF Voucher Reminder extension

document.addEventListener('DOMContentLoaded', function() {
  const addVoucherForm = document.getElementById('addVoucherForm');
  const voucherList = document.getElementById('voucherList');
  const totalVouchersSpan = document.getElementById('totalVouchers');
  const validVouchersSpan = document.getElementById('validVouchers');

  // Load and display vouchers
  loadVouchers();

  // Form submission
  addVoucherForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const code = document.getElementById('voucherCode').value.trim().toUpperCase();
    const expiryDate = document.getElementById('expiryDate').value;
    
    if (!code || !expiryDate) {
      alert('Please fill in both fields');
      return;
    }
    
    // Add new voucher
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];
      
      // Check for duplicate
      const exists = vouchers.some(v => v.code === code);
      if (exists) {
        alert('A voucher with this code already exists!');
        return;
      }
      
      const newVoucher = {
        id: Date.now().toString(),
        code: code,
        expiryDate: expiryDate,
        createdAt: new Date().toISOString()
      };
      
      vouchers.push(newVoucher);
      
      // Sort by expiry date (oldest first)
      vouchers.sort((a, b) => new Date(a.expiryDate) - new Date(b.expiryDate));
      
      browser.storage.local.set({ vouchers: vouchers }).then(function() {
        addVoucherForm.reset();
        loadVouchers();
      });
    });
  });

  // Load vouchers from storage
  function loadVouchers() {
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];
      renderVouchers(vouchers);
    });
  }

  // Render vouchers in the list
  function renderVouchers(vouchers) {
    if (vouchers.length === 0) {
      voucherList.innerHTML = '<p class="empty-message">No vouchers yet. Add one above!</p>';
      totalVouchersSpan.textContent = '0';
      validVouchersSpan.textContent = '0';
      return;
    }
    
    const now = new Date();
    now.setHours(0, 0, 0, 0); // Normalize to start of day
    
    let validCount = 0;
    let html = '';
    
    vouchers.forEach(function(voucher) {
      const expiryDate = new Date(voucher.expiryDate);
      const isValid = expiryDate >= now;
      
      if (isValid) validCount++;
      
      const expiryDateStr = formatDate(expiryDate);
      const isExpired = !isValid ? 'expired' : 'valid';
      
      html += `
        <div class="voucher-item ${isExpired}">
          <div>
            <div class="code">${voucher.code}</div>
            <div class="expiry">Expires: ${expiryDateStr}</div>
          </div>
          <div class="actions">
            <button class="btn btn-danger delete-btn" data-id="${voucher.id}">Delete</button>
          </div>
        </div>
      `;
    });
    
    voucherList.innerHTML = html;
    totalVouchersSpan.textContent = vouchers.length;
    validVouchersSpan.textContent = validCount;
    
    // Add event listeners to delete buttons
    document.querySelectorAll('.delete-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        const id = this.getAttribute('data-id');
        deleteVoucher(id);
      });
    });
  }

  // Delete a voucher
  function deleteVoucher(id) {
    if (!confirm('Are you sure you want to delete this voucher?')) {
      return;
    }
    
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];
      const updatedVouchers = vouchers.filter(v => v.id !== id);
      
      browser.storage.local.set({ vouchers: updatedVouchers }).then(function() {
        loadVouchers();
      });
    });
  }

  // Format date as DD/MM/YYYY
  function formatDate(date) {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    return `${day}/${month}/${year}`;
  }
});
