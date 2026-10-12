// Popup script for SNCF Voucher Reminder extension

document.addEventListener('DOMContentLoaded', function() {
  const addVoucherForm = document.getElementById('addVoucherForm');
  const voucherList = document.getElementById('voucherList');
  const totalVouchersSpan = document.getElementById('totalVouchers');
  const validVouchersSpan = document.getElementById('validVouchers');
  const statusMessage = document.getElementById('statusMessage');
  const expiryInput = document.getElementById('expiryDate');
  const calendarBtn = document.getElementById('calendarToggle');
  const calendarPanel = document.getElementById('calendarPanel');

  // Firefox cannot open its native date picker inside an extension popup,
  // so the date is a text field with this custom calendar widget
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December'];
  const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];
  let viewYear = new Date().getFullYear();
  let viewMonth = new Date().getMonth();

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

  // Parse DD/MM/YYYY (or ISO YYYY-MM-DD) text into an ISO date string,
  // or null when it is not a real calendar date
  function parseDateInput(str) {
    let m = str.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (m) return toISO(+m[3], +m[2], +m[1]);
    m = str.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
    if (m) return toISO(+m[1], +m[2], +m[3]);
    return null;
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
      showStatus('Enter a valid expiration date (DD/MM/YYYY).', 'error');
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
        closeCalendar();
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
