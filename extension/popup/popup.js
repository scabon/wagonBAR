// Popup script for SNCF Voucher Reminder extension

document.addEventListener('DOMContentLoaded', function() {
  const addVoucherForm = document.getElementById('addVoucherForm');
  const voucherList = document.getElementById('voucherList');
  const totalVouchersSpan = document.getElementById('totalVouchers');
  const validVouchersSpan = document.getElementById('validVouchers');
  const statusMessage = document.getElementById('statusMessage');

  // Load and display vouchers
  loadVouchers();

  // Show an inline status message (no native dialogs)
  function showStatus(text, type) {
    statusMessage.textContent = text;
    statusMessage.className = 'status-message' + (type ? ' ' + type : '');
    statusMessage.hidden = false;
  }

  function clearStatus() {
    statusMessage.hidden = true;
    statusMessage.textContent = '';
    statusMessage.className = 'status-message';
  }

  // Form submission
  addVoucherForm.addEventListener('submit', function(e) {
    e.preventDefault();

    const code = document.getElementById('voucherCode').value.trim().toUpperCase();
    const expiryDate = document.getElementById('expiryDate').value;

    if (!code || !expiryDate) {
      showStatus('Please fill in both fields.', 'error');
      return;
    }

    // Add new voucher
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];

      // Check for duplicate
      const exists = vouchers.some(v => v.code === code);
      if (exists) {
        showStatus('A voucher with this code already exists!', 'error');
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
        clearStatus();
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

  // Create an element with optional class and text
  function buildNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Render vouchers in the list
  function renderVouchers(vouchers) {
    if (vouchers.length === 0) {
      voucherList.replaceChildren(buildNode('p', 'empty-message', 'No vouchers yet. Add one above!'));
      totalVouchersSpan.textContent = '0';
      validVouchersSpan.textContent = '0';
      return;
    }

    const now = new Date();
    now.setHours(0, 0, 0, 0); // Normalize to start of day

    let validCount = 0;
    const frag = document.createDocumentFragment();

    vouchers.forEach(function(voucher) {
      const expiryDate = new Date(voucher.expiryDate);
      const isValid = expiryDate >= now;

      if (isValid) validCount++;

      const info = buildNode('div');
      info.appendChild(buildNode('div', 'code', voucher.code));
      info.appendChild(buildNode('div', 'expiry', 'Expires: ' + formatDate(expiryDate)));

      const deleteBtn = buildNode('button', 'btn btn-danger delete-btn', 'Delete');
      deleteBtn.dataset.id = voucher.id;

      const actions = buildNode('div', 'actions');
      actions.appendChild(deleteBtn);

      const item = buildNode('div', 'voucher-item ' + (isValid ? 'valid' : 'expired'));
      item.appendChild(info);
      item.appendChild(actions);
      frag.appendChild(item);
    });

    voucherList.replaceChildren(frag);
    totalVouchersSpan.textContent = vouchers.length;
    validVouchersSpan.textContent = validCount;
  }

  // Delete is a two-step action: first click arms the button,
  // a second click within a few seconds confirms
  voucherList.addEventListener('click', function(e) {
    const btn = e.target.closest('.delete-btn');
    if (!btn) return;

    if (btn.classList.contains('confirm')) {
      deleteVoucher(btn.dataset.id);
      return;
    }

    voucherList.querySelectorAll('.delete-btn.confirm').forEach(resetDeleteBtn);
    btn.classList.add('confirm');
    btn.textContent = 'Confirm?';
    setTimeout(function() { resetDeleteBtn(btn); }, 4000);
  });

  function resetDeleteBtn(btn) {
    btn.classList.remove('confirm');
    btn.textContent = 'Delete';
  }

  // Delete a voucher
  function deleteVoucher(id) {
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
