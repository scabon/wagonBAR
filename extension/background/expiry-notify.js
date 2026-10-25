// Expiry lead-time notification. A daily browser.alarms timer (plus a
// check at background startup and on settings/voucher changes) looks at
// every valid voucher and fires one system notification per voucher that
// expires within the configured lead time (settings.notifyLeadDays,
// default 7 days). Each voucher is notified once per expiry date: the
// expiryNotified map in storage.local remembers {voucherId: expiryDate},
// so editing a voucher to a new date re-arms it. Gated by the same
// settings.notifications toggle as the SNCF site arrival notification,
// plus its own settings.expiryNotifications checkbox (both default on).
// "Remind me tomorrow": clicking the notification (or its first button on
// Chromium, which supports buttons) snoozes that voucher for a day - the
// expirySnooze map in storage.local holds {voucherId: refireDate} - while
// dismissing it keeps the usual once-per-expiry-date behavior.
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
  const NOTIF_PREFIX = 'wagonbar-exp-';
  const SNOOZE_DAYS = 1;

  const MESSAGES = {
    en: {
      today: 'Your voucher {code} expires today.',
      soon: 'Your voucher {code} expires on {date} (in {days} {unit}).',
      unit: { one: 'day', many: 'days' },
      clickHint: 'Click to be reminded tomorrow.',
      snooze: 'Remind me tomorrow',
      dismiss: 'Dismiss'
    },
    fr: {
      today: 'Votre bon {code} expire aujourd\u2019hui.',
      soon: 'Votre bon {code} expire le {date} (dans {days} {unit}).',
      unit: { one: 'jour', many: 'jours' },
      clickHint: 'Cliquez pour \u00eatre rappel\u00e9 demain.',
      snooze: 'Me le rappeler demain',
      dismiss: 'Ignorer'
    }
  };

  // Notification buttons: Chromium only (MDN BCD - buttons and
  // onButtonClicked are false on Firefox); detected, never assumed
  const supportsButtons = !!(browser.notifications.onButtonClicked
      && browser.notifications.onButtonClicked.addListener);

  // Same language resolution as the popup and sncf-notify
  function resolveLanguage(setting) {
    if (setting === 'en' || setting === 'fr') return setting;
    return ((navigator.language || 'en').toLowerCase().indexOf('fr') === 0)
        ? 'fr' : 'en';
  }

  function messageFor(lang, code, date, daysLeft) {
    const dict = MESSAGES[lang] || MESSAGES.en;
    const template = daysLeft <= 0 ? dict.today : dict.soon;
    const unit = daysLeft === 1 ? dict.unit.one : dict.unit.many;
    return template.split('{code}').join(code).split('{date}').join(date)
        .split('{days}').join(daysLeft).split('{unit}').join(unit);
  }

  // Local date as YYYY-MM-DD (never toISOString: that shifts by the
  // timezone offset and would read as the wrong day)
  function isoDate(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')
        + '-' + String(d.getDate()).padStart(2, '0');
  }

  function leadDaysFrom(settings) {
    const n = parseInt(settings.notifyLeadDays, 10);
    if (isNaN(n)) return DEFAULT_LEAD_DAYS;
    return Math.min(MAX_LEAD_DAYS, Math.max(MIN_LEAD_DAYS, n));
  }

  async function checkExpiry() {
    try {
      const data = await browser.storage.local.get(
          ['settings', 'vouchers', 'expiryNotified', 'expirySnooze']);
      const settings = data.settings || {};
      if (settings.notifications === false) {
        return; // the notifications toggle in Settings is off
      }
      if (settings.expiryNotifications === false) {
        return; // the expiry-reminders checkbox in Settings is off
      }
      const leadDays = leadDaysFrom(settings);

      const vouchers = data.vouchers || [];
      const today = new Date();
      today.setHours(0, 0, 0, 0);

      const notified = data.expiryNotified || {};
      const snoozed = data.expirySnooze || {};
      const due = [];

      for (const voucher of vouchers) {
        // Parse as local midnight, same as getValidVouchers in
        // background.js (a date-only string reads as UTC otherwise)
        const expiry = new Date(voucher.expiryDate + 'T00:00:00');
        if (isNaN(expiry) || expiry < today) continue;
        const daysLeft = Math.round((expiry - today) / DAY_MS);
        if (daysLeft > leadDays) continue;
        if (snoozed[voucher.id]) {
          const refire = new Date(snoozed[voucher.id] + 'T00:00:00');
          if (!isNaN(refire) && refire > today) {
            continue; // snoozed ("remind me tomorrow"): silent until then
          }
        }
        if (notified[voucher.id] === voucher.expiryDate) {
          continue; // already notified for this expiry date
        }
        due.push({ voucher: voucher, daysLeft: daysLeft });
      }

      if (due.length > 0) {
        const lang = resolveLanguage(settings.language);
        const dict = MESSAGES[lang] || MESSAGES.en;
        let iconUrl = 'icons/icon-128.png';
        if (browser.runtime && browser.runtime.getURL) {
          iconUrl = browser.runtime.getURL('icons/icon-128.png');
        }
        for (const item of due) {
          const opts = {
            type: 'basic',
            iconUrl: iconUrl,
            title: 'wagonBar',
            message: messageFor(lang, item.voucher.code,
                                item.voucher.expiryDate, item.daysLeft)
          };
          if (supportsButtons) {
            opts.buttons = [
              { title: dict.snooze },
              { title: dict.dismiss }
            ];
          } else if (browser.notifications.onClicked
                     && browser.notifications.onClicked.addListener) {
            // without buttons (Firefox), the click-to-snooze action
            // needs to be discovered: spell it out in the message
            opts.message += ' ' + dict.clickHint;
          }
          await browser.notifications.create(
              NOTIF_PREFIX + item.voucher.id, opts);
          notified[item.voucher.id] = item.voucher.expiryDate;
          delete snoozed[item.voucher.id];
        }
      }

      // Prune entries for vouchers that no longer exist, then persist
      // (a voucher edited to a later date re-arms its notification)
      const alive = new Set(vouchers.map(v => v.id));
      for (const id of Object.keys(notified)) {
        if (!alive.has(id)) delete notified[id];
      }
      for (const id of Object.keys(snoozed)) {
        if (!alive.has(id)) delete snoozed[id];
      }
      await browser.storage.local.set(
          { expiryNotified: notified, expirySnooze: snoozed });
    } catch (e) {
      console.log('wagonBar: expiry notification check failed:', e);
    }
  }

  // "Remind me tomorrow": re-notify this voucher at the next daily check
  // after the snooze date (both keys are written atomically, so a snooze
  // can never leave a voucher in the notified-but-snoozed dead state)
  async function snooze(voucherId) {
    try {
      const data = await browser.storage.local.get(
          ['expiryNotified', 'expirySnooze']);
      const notified = data.expiryNotified || {};
      const snoozed = data.expirySnooze || {};
      delete notified[voucherId];
      const refire = new Date();
      refire.setHours(0, 0, 0, 0);
      refire.setDate(refire.getDate() + SNOOZE_DAYS);
      snoozed[voucherId] = isoDate(refire);
      await browser.storage.local.set(
          { expiryNotified: notified, expirySnooze: snoozed });
    } catch (e) {
      console.log('wagonBar: expiry snooze failed:', e);
    }
  }

  function voucherIdFromNotification(notificationId) {
    if (typeof notificationId !== 'string') return null;
    if (notificationId.indexOf(NOTIF_PREFIX) !== 0) return null;
    return notificationId.slice(NOTIF_PREFIX.length);
  }

  // Clicking the notification snoozes it (everywhere; on Chromium the
  // same action is also available as an explicit "Remind me tomorrow"
  // button). Dismissing - closing the notification, or its Dismiss
  // button - keeps the once-per-expiry-date behavior.
  if (browser.notifications.onClicked
      && browser.notifications.onClicked.addListener) {
    browser.notifications.onClicked.addListener(function (notificationId) {
      const voucherId = voucherIdFromNotification(notificationId);
      if (voucherId) snooze(voucherId);
    });
  }
  if (supportsButtons) {
    browser.notifications.onButtonClicked.addListener(
        function (notificationId, buttonIndex) {
          const voucherId = voucherIdFromNotification(notificationId);
          if (!voucherId) return;
          if (buttonIndex === 0) {
            snooze(voucherId);
          } else if (buttonIndex === 1 && browser.notifications.clear) {
            browser.notifications.clear(notificationId);
          }
        });
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
