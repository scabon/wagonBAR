// Popup script for the wagonBar extension

document.addEventListener('DOMContentLoaded', function() {
  const addVoucherForm = document.getElementById('addVoucherForm');
  const voucherList = document.getElementById('voucherList');
  const totalVouchersSpan = document.getElementById('totalVouchers');
  const validVouchersSpan = document.getElementById('validVouchers');
  const statusMessage = document.getElementById('statusMessage');
  const submitBtn = document.getElementById('submitBtn');
  const cancelEditBtn = document.getElementById('cancelEditBtn');
  const sortSelect = document.getElementById('sortOrder');
  const removeExpiredBtn = document.getElementById('removeExpiredBtn');
  const menuBtn = document.getElementById('menuBtn');
  const menuPanel = document.getElementById('menuPanel');
  const themeSelect = document.getElementById('themeSelect');
  const languageSelect = document.getElementById('languageSelect');
  const notificationsToggle = document.getElementById('notificationsToggle');
  const helpContent = document.getElementById('helpContent');
  const aboutContent = document.getElementById('aboutContent');

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

  // ---------------------------------------------------------------- i18n
  // English is the fallback; "system" resolves to the browser locale
  // (French when the browser is French, English otherwise)
  const STRINGS = {
    en: {
      appTitle: 'wagonBar \u2014 SNCF Vouchers',
      menuBtn: 'Menu',
      menuSettings: 'Settings',
      menuHelp: 'Help',
      menuAbout: 'About',
      addVoucherTitle: 'Add New Voucher',
      codeLabel: 'Code:',
      codePlaceholder: 'e.g., ABC123XYZ',
      expiryLabel: 'Expiration Date:',
      calendarAria: 'Pick a date from the calendar',
      calendarTitle: 'Pick a date',
      addVoucher: 'Add Voucher',
      updateVoucher: 'Update Voucher',
      cancel: 'Cancel',
      dismissHint: 'Click to dismiss',
      yourVouchers: 'Your Vouchers',
      removeExpired: 'Remove expired',
      confirmQuestion: 'Confirm?',
      sortByDate: 'By date',
      sortByCode: 'By code',
      sortOrder: 'Sort order',
      emptyMessage: 'No vouchers yet. Add one above!',
      statsTotal: 'Total',
      statsValid: 'Valid',
      statsVouchers: 'vouchers',
      settingsTheme: 'Theme',
      themeSystem: 'System',
      themeLight: 'Light',
      themeDark: 'Dark',
      settingsLanguage: 'Language',
      langSystem: 'System',
      settingsNotifications: 'SNCF site notification',
      settingsNotificationsHint: 'Show a reminder when you open sncf-connect.com with valid vouchers',
      errFillBoth: 'Please fill in both fields.',
      errValidDate: 'Enter a valid expiration date (YYYY-MM-DD).',
      errPastDate: 'The expiration date is in the past.',
      errDuplicate: 'A voucher with this code already exists!',
      statusUpdated: 'Voucher updated.',
      warnCodeLength: '"{code}" does not look like a usual {n}-character voucher code. Double-check it.',
      removedExpiredOne: 'Removed 1 expired voucher.',
      removedExpiredMany: 'Removed {n} expired vouchers.',
      edit: 'Edit',
      del: 'Delete',
      expiresPrefix: 'Expires: ',
      prevMonth: 'Previous month',
      nextMonth: 'Next month',
      back: 'Back',
      months: ['January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December'],
      weekdays: ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'],
      helpSections: [
        { title: 'Adding a voucher',
          text: 'Enter the voucher code and its expiration date, then press Add Voucher. The date format is YYYY-MM-DD; use the calendar button to pick a date.',
          items: [] },
        { title: 'Managing vouchers',
          text: '',
          items: ['Edit loads a voucher back into the form.',
                  'Delete is a two-step action: press it once, then Confirm.',
                  'Remove expired clears every expired voucher at once.'] },
        { title: 'Sync across devices',
          text: 'Vouchers replicate through your browser account (Firefox account on Firefox, Google/Microsoft account on Chromium) once the browser is signed in. Safari keeps everything local.',
          items: [] },
        { title: 'Privacy',
          text: 'wagonBar stores everything locally in your browser. It requests no network access and sends nothing anywhere.',
          items: [] }
      ],
      aboutTagline: 'A small reminder for your SNCF Connect vouchers.',
      aboutNote: 'Not affiliated with SNCF. Your vouchers stay in your own browser.',
      donateTitle: 'Support wagonBar',
      donateLiberapay: 'Donate on Liberapay',
      donateTipeee: 'Tip on Tipeee'
    },
    fr: {
      appTitle: 'wagonBar \u2014 Bons SNCF',
      menuBtn: 'Menu',
      menuSettings: 'Param\u00e8tres',
      menuHelp: 'Aide',
      menuAbout: '\u00c0 propos',
      addVoucherTitle: 'Ajouter un bon',
      codeLabel: 'Code :',
      codePlaceholder: 'ex. ABC123XYZ',
      expiryLabel: 'Date d\u2019expiration :',
      calendarAria: 'Choisir une date dans le calendrier',
      calendarTitle: 'Choisir une date',
      addVoucher: 'Ajouter',
      updateVoucher: 'Mettre \u00e0 jour',
      cancel: 'Annuler',
      dismissHint: 'Cliquer pour fermer',
      yourVouchers: 'Vos bons',
      removeExpired: 'Supprimer expir\u00e9s',
      confirmQuestion: 'Confirmer ?',
      sortByDate: 'Par date',
      sortByCode: 'Par code',
      sortOrder: 'Ordre de tri',
      emptyMessage: 'Aucun bon pour l\u2019instant. Ajoutez-en un ci-dessus !',
      statsTotal: 'Total',
      statsValid: 'Valides',
      statsVouchers: 'bons',
      settingsTheme: 'Th\u00e8me',
      themeSystem: 'Syst\u00e8me',
      themeLight: 'Clair',
      themeDark: 'Sombre',
      settingsLanguage: 'Langue',
      langSystem: 'Syst\u00e8me',
      settingsNotifications: 'Notification sur le site SNCF',
      settingsNotificationsHint: 'Affiche un rappel quand vous ouvrez sncf-connect.com avec des bons valides',
      errFillBoth: 'Veuillez remplir les deux champs.',
      errValidDate: 'Saisissez une date d\u2019expiration valide (AAAA-MM-JJ).',
      errPastDate: 'La date d\u2019expiration est dans le pass\u00e9.',
      errDuplicate: 'Un bon avec ce code existe d\u00e9j\u00e0 !',
      statusUpdated: 'Bon mis \u00e0 jour.',
      warnCodeLength: '\u00ab {code} \u00bb ne ressemble pas \u00e0 un code de bon habituel de {n} caract\u00e8res. V\u00e9rifiez-le.',
      removedExpiredOne: '1 bon expir\u00e9 supprim\u00e9.',
      removedExpiredMany: '{n} bons expir\u00e9s supprim\u00e9s.',
      edit: 'Modifier',
      del: 'Supprimer',
      expiresPrefix: 'Expire : ',
      prevMonth: 'Mois pr\u00e9c\u00e9dent',
      nextMonth: 'Mois suivant',
      back: 'Retour',
      months: ['janvier', 'f\u00e9vrier', 'mars', 'avril', 'mai', 'juin',
               'juillet', 'ao\u00fbt', 'septembre', 'octobre', 'novembre', 'd\u00e9cembre'],
      weekdays: ['Lu', 'Ma', 'Me', 'Je', 'Ve', 'Sa', 'Di'],
      helpSections: [
        { title: 'Ajouter un bon',
          text: 'Saisissez le code du bon et sa date d\u2019expiration, puis appuyez sur Ajouter. Le format de date est AAAA-MM-JJ ; utilisez le bouton calendrier pour choisir une date.',
          items: [] },
        { title: 'G\u00e9rer les bons',
          text: '',
          items: ['Modifier recharge un bon dans le formulaire.',
                  'Supprimer se fait en deux temps : un premier appui, puis Confirmer.',
                  'Supprimer expir\u00e9s efface d\u2019un coup tous les bons expir\u00e9s.'] },
        { title: 'Synchronisation entre appareils',
          text: 'Les bons se r\u00e9pliquent via le compte du navigateur (compte Firefox sur Firefox, compte Google/Microsoft sur Chromium) quand le navigateur est connect\u00e9. Safari reste local.',
          items: [] },
        { title: 'Confidentialit\u00e9',
          text: 'wagonBar stocke tout localement dans votre navigateur. Il n\u2019acc\u00e8de \u00e0 aucun r\u00e9seau et n\u2019envoie rien nulle part.',
          items: [] }
      ],
      aboutTagline: 'Un petit rappel pour vos bons SNCF Connect.',
      aboutNote: 'Non affili\u00e9 \u00e0 la SNCF. Vos bons restent dans votre navigateur.',
      donateTitle: 'Soutenir wagonBar',
      donateLiberapay: 'Soutenir sur Liberapay',
      donateTipeee: 'Pourboire sur Tipeee'
    }
  };

  // Donation links (see AGENTS.md, Donations section)
  const DONATION_LIBERAPAY = 'https://liberapay.com/cabon14/';
  const DONATION_TIPEEE = 'https://fr.tipeee.com/cabon14/';

  let currentLang = 'en';

  function t(key, params) {
    let s = (STRINGS[currentLang] && STRINGS[currentLang][key]) ||
             STRINGS.en[key];
    if (s === undefined) return key;
    if (params) {
      Object.keys(params).forEach(function(name) {
        s = s.split('{' + name + '}').join(params[name]);
      });
    }
    return s;
  }

  // Apply the current language to every tagged node in the static markup
  function applyI18n() {
    document.documentElement.lang = currentLang === 'fr' ? 'fr' : 'en';
    document.querySelectorAll('[data-i18n]').forEach(function(node) {
      node.textContent = t(node.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(node) {
      node.placeholder = t(node.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(function(node) {
      node.title = t(node.dataset.i18nTitle);
    });
    document.querySelectorAll('[data-i18n-label]').forEach(function(node) {
      node.setAttribute('aria-label', t(node.dataset.i18nLabel));
    });
  }

  // ------------------------------------------------------------- settings
  const DEFAULT_SETTINGS = {
    theme: 'system',      // 'system' | 'light' | 'dark'
    language: 'system',   // 'system' | 'en' | 'fr'
    notifications: true
  };
  let settings = Object.assign({}, DEFAULT_SETTINGS);

  const darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
  if (darkMedia && darkMedia.addEventListener) {
    darkMedia.addEventListener('change', function() {
      if (settings.theme === 'system') applyTheme();
    });
  }

  // The CSS only ever sees "light" or "dark": "system" is resolved here
  function applyTheme() {
    const resolved = settings.theme === 'system'
        ? (darkMedia && darkMedia.matches ? 'dark' : 'light')
        : settings.theme;
    document.documentElement.setAttribute('data-theme', resolved);
  }

  function applyLanguage() {
    currentLang = resolveLanguage(settings.language);
    applyI18n();
    buildHelpContent();
    buildAboutContent();
    // Dynamic labels and any rendered vouchers must follow the language
    submitBtn.textContent = editingId ? t('updateVoucher') : t('addVoucher');
    loadVouchers();
  }

  function resolveLanguage(setting) {
    if (setting === 'en' || setting === 'fr') return setting;
    return ((navigator.language || 'en').toLowerCase().indexOf('fr') === 0)
        ? 'fr' : 'en';
  }

  function loadSettings() {
    browser.storage.local.get('settings').then(function(data) {
      settings = Object.assign({}, DEFAULT_SETTINGS, data.settings || {});
      themeSelect.value = settings.theme;
      languageSelect.value = settings.language;
      notificationsToggle.checked = settings.notifications;
      applyTheme();
      applyLanguage();
    });
  }

  function saveSettings() {
    browser.storage.local.set({ settings: settings });
  }

  themeSelect.addEventListener('change', function() {
    settings.theme = themeSelect.value;
    applyTheme();
    saveSettings();
  });

  languageSelect.addEventListener('change', function() {
    settings.language = languageSelect.value;
    applyLanguage();
    saveSettings();
  });

  notificationsToggle.addEventListener('change', function() {
    settings.notifications = notificationsToggle.checked;
    saveSettings();
  });

  // ---------------------------------------------------------------- views
  const VIEWS = ['view-main', 'view-settings', 'view-help', 'view-about'];

  function showView(id) {
    VIEWS.forEach(function(view) {
      document.getElementById(view).hidden = (view !== id);
    });
  }

  function openMenu() {
    menuPanel.hidden = false;
    menuBtn.classList.add('open');
  }

  function closeMenu() {
    menuPanel.hidden = true;
    menuBtn.classList.remove('open');
  }

  menuBtn.addEventListener('click', function(e) {
    e.stopPropagation();
    if (menuPanel.hidden) openMenu();
    else closeMenu();
  });

  menuPanel.addEventListener('click', function(e) {
    const btn = e.target.closest('button');
    if (!btn) return;
    closeMenu();
    showView('view-' + btn.id.replace('menu', '').toLowerCase());
  });

  document.querySelectorAll('[data-back]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      showView('view-main');
    });
  });

  // -------------------------------------------------------------- content
  function buildHelpContent() {
    const frag = document.createDocumentFragment();
    t('helpSections').forEach(function(section) {
      const h = document.createElement('h2');
      h.textContent = section.title;
      frag.appendChild(h);
      if (section.text) {
        const p = document.createElement('p');
        p.textContent = section.text;
        frag.appendChild(p);
      }
      if (section.items && section.items.length) {
        const ul = document.createElement('ul');
        section.items.forEach(function(item) {
          const li = document.createElement('li');
          li.textContent = item;
          ul.appendChild(li);
        });
        frag.appendChild(ul);
      }
    });
    helpContent.replaceChildren(frag);
  }

  function buildAboutContent() {
    const name = buildNode('p', 'about-name', 'wagonBar');
    let version = '';
    try {
      if (browser.runtime && browser.runtime.getManifest) {
        version = browser.runtime.getManifest().version;
      }
    } catch (e) {
      // not running as a real extension (e.g. the e2e test page)
    }
    const versionNode = buildNode('p', 'about-version',
                                  version ? 'Version ' + version : '');
    const tagline = buildNode('p', '', t('aboutTagline'));
    const note = buildNode('p', 'about-note', t('aboutNote'));

    const donateTitle = buildNode('h2', '', t('donateTitle'));
    const liberapay = document.createElement('a');
    liberapay.href = DONATION_LIBERAPAY;
    liberapay.target = '_blank';
    liberapay.rel = 'noopener noreferrer';
    liberapay.className = 'donate-liberapay';
    liberapay.textContent = t('donateLiberapay');
    const tipeee = document.createElement('a');
    tipeee.href = DONATION_TIPEEE;
    tipeee.target = '_blank';
    tipeee.rel = 'noopener noreferrer';
    tipeee.className = 'donate-tipeee';
    tipeee.textContent = t('donateTipeee');
    const donateRow = buildNode('div', 'donate-row');
    donateRow.appendChild(liberapay);
    donateRow.appendChild(tipeee);

    aboutContent.replaceChildren(name, versionNode, tagline, note,
                                 donateTitle, donateRow);
  }

  // Firefox cannot open its native date picker inside an extension popup,
  // so the date is a text field with this custom calendar widget
  let viewYear = new Date().getFullYear();
  let viewMonth = new Date().getMonth();

  // Load settings, vouchers and display
  applyTheme();
  loadSettings();
  loadVouchers();
  updateGhost();

  // Re-render when the voucher list changes from outside this popup
  // (a cross-device sync merge done by the background script)
  if (browser.storage.onChanged) {
    browser.storage.onChanged.addListener(function (changes, area) {
      if (area === 'local' && changes.vouchers) {
        loadVouchers();
      }
    });
  }

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
      showStatus(t('errFillBoth'), 'error');
      return;
    }

    const expiryDate = parseDateInput(rawDate);
    if (!expiryDate) {
      showStatus(t('errValidDate'), 'error');
      return;
    }

    // A voucher that expires today is still valid, anything earlier is not
    const now = new Date();
    const today = toISO(now.getFullYear(), now.getMonth() + 1, now.getDate());
    if (expiryDate < today) {
      showStatus(t('errPastDate'), 'error');
      return;
    }

    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];

      if (editingId) {
        // Update the edited voucher (its own code doesn't count as duplicate)
        const duplicate = vouchers.some(v => v.code === code && v.id !== editingId);
        if (duplicate) {
          showStatus(t('errDuplicate'), 'error');
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
          showStatus(t('statusUpdated'), 'success');
          syncWriteVoucher(edited);
        });
        return;
      }

      // Add new voucher

      // Check for duplicate
      const exists = vouchers.some(v => v.code === code);
      if (exists) {
        showStatus(t('errDuplicate'), 'error');
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
        syncWriteVoucher(newVoucher);
      });
    });
  });

  // Warn (without blocking) when the code doesn't look like a usual
  // voucher code, as soon as the user leaves the code field
  document.getElementById('voucherCode').addEventListener('blur', function() {
    const code = this.value.trim().toUpperCase();
    if (code && code.length !== EXPECTED_CODE_LENGTH) {
      const shown = code.length > 12 ? code.slice(0, 12) + '\u2026' : code;
      showStatus(t('warnCodeLength', { code: shown, n: EXPECTED_CODE_LENGTH }), 'warning');
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
      submitBtn.textContent = t('updateVoucher');
      cancelEditBtn.hidden = false;
      document.getElementById('voucherCode').focus();
    });
  }

  function cancelEdit() {
    editingId = null;
    addVoucherForm.reset();
    updateGhost();
    submitBtn.textContent = t('addVoucher');
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
    prevBtn.title = t('prevMonth');
    nextBtn.title = t('nextMonth');
    const title = buildNode('span', 'calendar-title',
                            t('months')[viewMonth] + ' ' + viewYear);
    header.appendChild(prevBtn);
    header.appendChild(title);
    header.appendChild(nextBtn);
    calendarPanel.appendChild(header);

    const grid = buildNode('div', 'calendar-grid');
    t('weekdays').forEach(function(weekday) {
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
      // Past days cannot be picked (a voucher expiring today is allowed)
      if (iso < todayISO) dayBtn.disabled = true;
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

  // Close the calendar and the menu when clicking elsewhere in the popup
  // or pressing Escape
  document.addEventListener('click', function(e) {
    if (!calendarPanel.hidden && !calendarPanel.contains(e.target) &&
        !calendarBtn.contains(e.target)) {
      closeCalendar();
    }
    if (!menuPanel.hidden && !menuPanel.contains(e.target) &&
        !menuBtn.contains(e.target)) {
      closeMenu();
    }
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeCalendar();
      closeMenu();
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
      voucherList.replaceChildren(buildNode('p', 'empty-message', t('emptyMessage')));
      totalVouchersSpan.textContent = '0';
      validVouchersSpan.textContent = '0';
      removeExpiredBtn.hidden = true;
      return;
    }

    const now = new Date();
    now.setHours(0, 0, 0, 0); // Normalize to start of day

    let validCount = 0;
    let expiredCount = 0;
    const frag = document.createDocumentFragment();

    sorted.forEach(function(voucher) {
      // Parse as local midnight: a date-only string would be read as UTC
      // and make a voucher expiring today look already expired depending
      // on the timezone
      const expiryDate = new Date(voucher.expiryDate + 'T00:00:00');
      const isValid = expiryDate >= now;

      if (isValid) validCount++;
      else expiredCount++;

      const info = buildNode('div');
      info.appendChild(buildNode('div', 'code', voucher.code));
      info.appendChild(buildNode('div', 'expiry', t('expiresPrefix') + formatDate(expiryDate)));

      const editBtn = buildNode('button', 'btn btn-secondary edit-btn', t('edit'));
      editBtn.dataset.id = voucher.id;

      const deleteBtn = buildNode('button', 'btn btn-danger delete-btn', t('del'));
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

    // The bulk-clear action only makes sense when an expired voucher exists
    removeExpiredBtn.hidden = expiredCount === 0;
    if (removeExpiredBtn.hidden) resetRemoveExpiredBtn();
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
    btn.textContent = t('confirmQuestion');
    setTimeout(function() { resetDeleteBtn(btn); }, 4000);
  });

  function resetDeleteBtn(btn) {
    btn.classList.remove('confirm');
    btn.textContent = t('del');
  }

  // Delete a voucher
  function deleteVoucher(id) {
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];
      const updatedVouchers = vouchers.filter(v => v.id !== id);

      browser.storage.local.set({ vouchers: updatedVouchers }).then(function() {
        loadVouchers();
        syncWriteVoucher({ id: id }, true);
      });
    });
  }

  // Remove expired uses the same two-step confirm as the single delete
  removeExpiredBtn.addEventListener('click', function() {
    if (removeExpiredBtn.classList.contains('confirm')) {
      resetRemoveExpiredBtn();
      removeExpiredVouchers();
      return;
    }

    removeExpiredBtn.classList.add('confirm');
    removeExpiredBtn.textContent = t('confirmQuestion');
    setTimeout(function() { resetRemoveExpiredBtn(); }, 4000);
  });

  function resetRemoveExpiredBtn() {
    removeExpiredBtn.classList.remove('confirm');
    removeExpiredBtn.textContent = t('removeExpired');
  }

  // Delete every expired voucher; each deletion is mirrored to the sync
  // area as a tombstone, exactly like a single delete
  function removeExpiredVouchers() {
    browser.storage.local.get('vouchers').then(function(data) {
      const vouchers = data.vouchers || [];
      const now = new Date();
      now.setHours(0, 0, 0, 0);
      const expired = vouchers.filter(v => new Date(v.expiryDate + 'T00:00:00') < now);
      if (expired.length === 0) return;

      const expiredIds = {};
      expired.forEach(function(v) { expiredIds[v.id] = true; });
      const updatedVouchers = vouchers.filter(v => !expiredIds[v.id]);

      browser.storage.local.set({ vouchers: updatedVouchers }).then(function() {
        if (editingId && expiredIds[editingId]) cancelEdit();
        loadVouchers();
        showStatus(expired.length === 1 ? t('removedExpiredOne')
                                        : t('removedExpiredMany', { n: expired.length }),
                   'success');
        expired.forEach(function(v) { syncWriteVoucher({ id: v.id }, true); });
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
