// Popup script for SNCF Voucher Reminder extension

document.addEventListener('DOMContentLoaded', function() {
  const addVoucherForm = document.getElementById('addVoucherForm');
  const voucherList = document.getElementById('voucherList');
  const totalVouchersSpan = document.getElementById('totalVouchers');
  const validVouchersSpan = document.getElementById('validVouchers');
  const statusMessage = document.getElementById('statusMessage');
  const submitBtn = document.getElementById('submitBtn');
  const cancelEditBtn = document.getElementById('cancelEditBtn');
  const sortSelect = document.getElementById('sortOrder');

  // Voucher currently being edited in the form, null when adding
  let editingId = null;
  // Auto-dismiss timer for transient status messages
  let statusTimer = null;
  const expiryInput = document.getElementById('expiryDate');
  const calendarBtn = document.getElementById('calendarToggle');
  const calendarPanel = document.getElementById('calendarPanel');
  const expiryGhost = document.getElementById('expiryGhost');

  // Usual SNCF voucher code length (may evolve, only used for a warning)
  const EXPECTED_CODE_LENGTH = 9;
  // Date entry pattern shown as the grey hint while typing
  const DATE_PATTERN = 'YYYY-MM-DD';

  // Firefox cannot open its native date picker inside an extension popup,
  // so the date is a text field with this custom calendar widget
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];
  const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  let viewYear = new Date().getFullYear();
  let viewMonth = new Date().getMonth();

  // Load and display vouchers
  loadVouchers();
  updateGhost();

  // Show an inline status message (no native dialogs). Warnings and
  // successes are transient: they auto-dismiss and can be clicked away.
  // Errors stay until the next action.
  function showStatus(text, type) {
    clearTimeout(statusTimer);
    statusMessage.textContent = text;
    statusMessage.className = 'status-message' + (type ? ' ' + type : '');
    statusMessage.hidden = false;
    if (type === 'success' || type === 'warning') {
      statusTimer = setTimeout(clearStatus, 4000);
    }
  }

  function clearStatus() {
    clearTimeout(statusTimer);
    statusMessage.hidden = true;
    statusMessage.textContent = '';
    statusMessage.className = 'status-message';
  }

  statusMessage.addEventListener('click', clearStatus);

  // Parse ISO (YYYY-MM-DD) text into an ISO date string,
  // or null when it is not a real calendar date
  function parseDateInput(str) {
    const m = str.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (!m) return null;
    return toISO(+m[1], +m[2], +m[3]);
  }

  // Build an ISO date string, or null when the day/month/year combination
  // does not exist (e.g. February 31st)
  function toISO(year, month, day) {
    const date = new Date(year, month - 1, day);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 ||
        date.getDate() !== day) {
      return null;
    }
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  // Auto-insert the dashes while typing and keep a grey hint showing the
  // remaining part of the date pattern behind the typed text
  expiryInput.addEventListener('input', function() {
    const digits = expiryInput.value.replace(/\D/g, '').slice(0, 8);
    let formatted = digits.slice(0, 4);
    if (digits.length >= 4) formatted += '-' + digits.slice(4, 6);
    if (digits.length >= 6) formatted += '-' + digits.slice(6);
    expiryInput.value = formatted;
    updateGhost();
  });

  function updateGhost() {
    const value = expiryInput.value;
    if (!value || value.length >= DATE_PATTERN.length) {
      expiryGhost.textContent = '';
      return;
    }
    const typed = document.createElement('span');
    typed.className = 'ghost-typed';
    typed.textContent = value;
    const rest = document.createElement('span');
    rest.className = 'ghost-rest';
    rest.textContent = DATE_PATTERN.slice(value.length);
    expiryGhost.replaceChildren(typed, rest);
  }

  // Form submission
  addVoucherForm.addEventListener('submit', function(e) {
    e.preventDefault();

    const code = document.getElementById('voucherCode').value.trim().toUpperCase();
    const rawDate = expiryInput.value.trim();

    if (!code || !rawDate) {
      showStatus('Please fill in both fields.', 'error');
      return;
    }

    const expiryDate = parseDateInput(rawDate);
    if (!expiryDate) {
      showStatus('Enter a valid expiration date (YYYY-MM-DD).', 'error');
      return;
    }

    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];

      if (editingId) {
        // Update the edited voucher (its own code doesn't count as duplicate)
        const duplicate = vouchers.some(v => v.code === code && v.id !== editingId);
        if (duplicate) {
          showStatus('A voucher with this code already exists!', 'error');
          return;
        }
        const edited = vouchers.find(v => v.id === editingId);
        if (!edited) {
          cancelEdit();
          return;
        }
        edited.code = code;
        edited.expiryDate = expiryDate;
        vouchers.sort((a, b) => new Date(a.expiryDate) - new Date(b.expiryDate));
        browser.storage.local.set({ vouchers: vouchers }).then(function() {
          cancelEdit();
          loadVouchers();
          showStatus('Voucher updated.', 'success');
        });
        return;
      }

      // Add new voucher

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
        closeCalendar();
        updateGhost();
        loadVouchers();
      });
    });
  });

  // Warn (without blocking) when the code doesn't look like a usual
  // voucher code, as soon as the user leaves the code field
  document.getElementById('voucherCode').addEventListener('blur', function() {
    const code = this.value.trim().toUpperCase();
    if (code && code.length !== EXPECTED_CODE_LENGTH) {
      const shown = code.length > 12 ? code.slice(0, 12) + '\u2026' : code;
      showStatus('"' + shown + '" does not look like a usual ' +
                  EXPECTED_CODE_LENGTH + '-character voucher code. ' +
                  'Double-check it.', 'warning');
    } else {
      clearStatus();
    }
  });

  // Editing: load a voucher into the form, or leave edit mode
  function startEdit(id) {
    browser.storage.local.get('vouchers').then(function(data) {
      const voucher = (data.vouchers || []).find(v => v.id === id);
      if (!voucher) return;
      editingId = id;
      document.getElementById('voucherCode').value = voucher.code;
      expiryInput.value = voucher.expiryDate;
      updateGhost();
      submitBtn.textContent = 'Update Voucher';
      cancelEditBtn.hidden = false;
      document.getElementById('voucherCode').focus();
    });
  }

  function cancelEdit() {
    editingId = null;
    addVoucherForm.reset();
    updateGhost();
    submitBtn.textContent = 'Add Voucher';
    cancelEditBtn.hidden = true;
    clearStatus();
  }

  cancelEditBtn.addEventListener('click', cancelEdit);

  voucherList.addEventListener('click', function(e) {
    const btn = e.target.closest('.edit-btn');
    if (!btn) return;
    startEdit(btn.dataset.id);
  });

  // Load vouchers from storage, applying the remembered sort order
  function loadVouchers() {
    browser.storage.local.get(['vouchers', 'sortOrder']).then(function(data) {
      sortSelect.value = data.sortOrder === 'code' ? 'code' : 'date';
      renderVouchers(data.vouchers || []);
    });
  }

  sortSelect.addEventListener('change', function() {
    browser.storage.local.set({ sortOrder: sortSelect.value }).then(loadVouchers);
  });

  // Create an element with optional class and text
  function buildNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Render the month grid of the calendar widget
  function renderCalendar() {
    calendarPanel.replaceChildren();

    const header = buildNode('div', 'calendar-header');
    const prevBtn = buildNode('button', 'calendar-nav', '\u2039');
    const nextBtn = buildNode('button', 'calendar-nav', '\u203A');
    prevBtn.type = 'button';
    nextBtn.type = 'button';
    prevBtn.title = 'Previous month';
    nextBtn.title = 'Next month';
    const title = buildNode('span', 'calendar-title',
                            MONTHS[viewMonth] + ' ' + viewYear);
    header.appendChild(prevBtn);
    header.appendChild(title);
    header.appendChild(nextBtn);
    calendarPanel.appendChild(header);

    const grid = buildNode('div', 'calendar-grid');
    WEEKDAYS.forEach(function(weekday) {
      grid.appendChild(buildNode('span', 'calendar-weekday', weekday));
    });

    // Blank cells before the first day (Monday-first grid)
    const startCol = (new Date(viewYear, viewMonth, 1).getDay() + 6) % 7;
    for (let i = 0; i < startCol; i++) {
      grid.appendChild(buildNode('span', 'calendar-blank'));
    }

    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const selected = parseDateInput(expiryInput.value.trim());
    const now = new Date();
    const todayISO = toISO(now.getFullYear(), now.getMonth() + 1, now.getDate());
    for (let day = 1; day <= daysInMonth; day++) {
      const iso = toISO(viewYear, viewMonth + 1, day);
      const dayBtn = buildNode('button', 'calendar-day', String(day));
      dayBtn.type = 'button';
      dayBtn.dataset.date = iso;
      if (iso === selected) dayBtn.classList.add('selected');
      if (iso === todayISO) dayBtn.classList.add('today');
      grid.appendChild(dayBtn);
    }
    calendarPanel.appendChild(grid);

    prevBtn.addEventListener('click', function() {
      viewMonth--;
      if (viewMonth < 0) { viewMonth = 11; viewYear--; }
      renderCalendar();
    });
    nextBtn.addEventListener('click', function() {
      viewMonth++;
      if (viewMonth > 11) { viewMonth = 0; viewYear++; }
      renderCalendar();
    });

    grid.addEventListener('click', function(e) {
      const dayBtn = e.target.closest('.calendar-day');
      if (!dayBtn) return;
      const picked = new Date(dayBtn.dataset.date + 'T00:00:00');
      expiryInput.value = formatDate(picked);
      updateGhost();
      closeCalendar();
    });
  }

  function openCalendar() {
    const parsed = parseDateInput(expiryInput.value.trim());
    if (parsed) {
      const current = new Date(parsed + 'T00:00:00');
      viewYear = current.getFullYear();
      viewMonth = current.getMonth();
    } else {
      const now = new Date();
      viewYear = now.getFullYear();
      viewMonth = now.getMonth();
    }
    renderCalendar();
    calendarPanel.hidden = false;
  }

  function closeCalendar() {
    calendarPanel.hidden = true;
  }

  calendarBtn.addEventListener('click', function() {
    if (calendarPanel.hidden) {
      openCalendar();
    } else {
      closeCalendar();
    }
  });

  // Close when clicking elsewhere in the popup or pressing Escape
  document.addEventListener('click', function(e) {
    if (!calendarPanel.hidden && !calendarPanel.contains(e.target) &&
        !calendarBtn.contains(e.target)) {
      closeCalendar();
    }
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeCalendar();
    }
  });

  // Render vouchers in the list, sorted by date or by code
  function renderVouchers(vouchers) {
    const sorted = vouchers.slice();
    if (sortSelect.value === 'code') {
      sorted.sort((a, b) => a.code.localeCompare(b.code));
    } else {
      sorted.sort((a, b) => new Date(a.expiryDate) - new Date(b.expiryDate));
    }

    if (sorted.length === 0) {
      voucherList.replaceChildren(buildNode('p', 'empty-message', 'No vouchers yet. Add one above!'));
      totalVouchersSpan.textContent = '0';
      validVouchersSpan.textContent = '0';
      return;
    }

    const now = new Date();
    now.setHours(0, 0, 0, 0); // Normalize to start of day

    let validCount = 0;
    const frag = document.createDocumentFragment();

    sorted.forEach(function(voucher) {
      // Parse as local midnight: a date-only string would be read as UTC
      // and make a voucher expiring today look already expired depending
      // on the timezone
      const expiryDate = new Date(voucher.expiryDate + 'T00:00:00');
      const isValid = expiryDate >= now;

      if (isValid) validCount++;

      const info = buildNode('div');
      info.appendChild(buildNode('div', 'code', voucher.code));
      info.appendChild(buildNode('div', 'expiry', 'Expires: ' + formatDate(expiryDate)));

      const editBtn = buildNode('button', 'btn btn-secondary edit-btn', 'Edit');
      editBtn.dataset.id = voucher.id;

      const deleteBtn = buildNode('button', 'btn btn-danger delete-btn', 'Delete');
      deleteBtn.dataset.id = voucher.id;

      const actions = buildNode('div', 'actions');
      actions.appendChild(editBtn);
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

  // Format date as ISO YYYY-MM-DD
  function formatDate(date) {
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const year = date.getFullYear();
    return `${year}-${month}-${day}`;
  }
});
