// Expiry lead-time notification. A daily browser.alarms timer (plus a
// check at background startup and on settings/voucher changes) looks at
// every valid voucher and fires one system notification per voucher that
// expires within the configured lead time (settings.notifyLeadDays,
// default 7 days). Each voucher is notified once per expiry date: the
// expiryNotified map in storage.local remembers {voucherId: expiryDate},
// so editing a voucher to a new date re-arms it. Gated by the same
// settings.notifications toggle as the SNCF site arrival notification.
// Safari has no notifications API (MDN BCD), so this degrades to a
// no-op there; without browser.alarms (old engines) it stays dormant.

(function () {
  if (!browser.alarms || !browser.alarms.onAlarm || !browser.notifications) {
    return; // no alarms or notifications API: stay dormant
  }

  const ALARM_NAME = 'wagonbar-expiry-check';
  const DAY_MS = 24 * 60 * 60 * 1000;
  const DEFAULT_LEAD_DAYS = 7;
  const MIN_LEAD_DAYS = 1;
  const MAX_LEAD_DAYS = 30;

  const MESSAGES = {
    en: {
      today: 'Your voucher {code} expires today.',
      soon: 'Your voucher {code} expires on {date}.'
    },
    fr: {
      today: 'Votre bon {code} expire aujourd\u2019hui.',
      soon: 'Votre bon {code} expire le {date}.'
    }
  };

  // Same language resolution as the popup and sncf-notify
  function resolveLanguage(setting) {
    if (setting === 'en' || setting === 'fr') return setting;
    return ((navigator.language || 'en').toLowerCase().indexOf('fr') === 0)
        ? 'fr' : 'en';
  }

  function messageFor(lang, code, date, daysLeft) {
    const dict = MESSAGES[lang] || MESSAGES.en;
    const template = daysLeft <= 0 ? dict.today : dict.soon;
    return template.split('{code}').join(code).split('{date}').join(date);
  }

  function leadDaysFrom(settings) {
    const n = parseInt(settings.notifyLeadDays, 10);
    if (isNaN(n)) return DEFAULT_LEAD_DAYS;
    return Math.min(MAX_LEAD_DAYS, Math.max(MIN_LEAD_DAYS, n));
  }

  async function checkExpiry() {
    try {
      const data = await browser.storage.local.get(
          ['settings', 'vouchers', 'expiryNotified']);
      const settings = data.settings || {};
      if (settings.notifications === false) {
        return; // the notifications toggle in Settings is off
      }
      const leadDays = leadDaysFrom(settings);

      const vouchers = data.vouchers || [];
      const today = new Date();
      today.setHours(0, 0, 0, 0);

      const notified = data.expiryNotified || {};
      const due = [];

      for (const voucher of vouchers) {
        // Parse as local midnight, same as getValidVouchers in
        // background.js (a date-only string reads as UTC otherwise)
        const expiry = new Date(voucher.expiryDate + 'T00:00:00');
        if (isNaN(expiry) || expiry < today) continue;
        const daysLeft = Math.round((expiry - today) / DAY_MS);
        if (daysLeft > leadDays) continue;
        if (notified[voucher.id] === voucher.expiryDate) {
          continue; // already notified for this expiry date
        }
        due.push({ voucher: voucher, daysLeft: daysLeft });
      }

      if (due.length > 0) {
        const lang = resolveLanguage(settings.language);
        let iconUrl = 'icons/icon-128.png';
        if (browser.runtime && browser.runtime.getURL) {
          iconUrl = browser.runtime.getURL('icons/icon-128.png');
        }
        for (const item of due) {
          await browser.notifications.create({
            type: 'basic',
            iconUrl: iconUrl,
            title: 'wagonBar',
            message: messageFor(lang, item.voucher.code,
                                item.voucher.expiryDate, item.daysLeft)
          });
          notified[item.voucher.id] = item.voucher.expiryDate;
        }
      }

      // Prune entries for vouchers that no longer exist, then persist
      // (a voucher edited to a later date re-arms its notification)
      const alive = new Set(vouchers.map(v => v.id));
      for (const id of Object.keys(notified)) {
        if (!alive.has(id)) delete notified[id];
      }
      await browser.storage.local.set({ expiryNotified: notified });
    } catch (e) {
      console.log('wagonBar: expiry notification check failed:', e);
    }
  }

  // Daily alarm (the event page / service worker cannot rely on
  // setTimeout), plus a check at every background start so a browser
  // closed at the daily tick still catches up
  browser.alarms.create(ALARM_NAME, { periodInMinutes: 60 * 24 });
  browser.alarms.onAlarm.addListener(function (alarm) {
    if (alarm && alarm.name === ALARM_NAME) checkExpiry();
  });
  checkExpiry();

  // Settings or voucher list changes take effect immediately (a newly
  // added voucher expiring soon, or a raised lead time, notifies right
  // away instead of waiting for the daily tick)
  browser.storage.onChanged.addListener(function (changes, area) {
    if (area === 'local' && (changes.settings || changes.vouchers)) {
      checkExpiry();
    }
  });
})();
