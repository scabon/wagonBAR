// SNCF site arrival notification. When the user opens sncf-connect.com
// with at least one valid voucher, fire one system notification
// ("You have N valid vouchers"). No content script and no host
// permission: the tabs permission only lets the background script read
// tab URLs (v1.3 privacy stance).
// Safari has no webextensions notifications API at all (MDN BCD), so
// this degrades to a no-op there.

(function () {
  if (!browser.notifications || !browser.tabs || !browser.tabs.onUpdated) {
    return; // no notifications API (Safari) or unexpected environment
  }

  // sncf-connect.com and all its subdomains
  const SNCF_HOST_RE = /(^|\.)sncf-connect\.com$/i;

  // One notification per tab visit: the tab is marked when notified and
  // only notified again after it leaves the site or is closed. SPA
  // pushState navigation never fires status "complete", so in-site route
  // changes stay silent.
  const notifiedTabs = new Set();

  const MESSAGES = {
    en: {
      one: 'You have 1 valid voucher.',
      many: 'You have {n} valid vouchers.',
      soonest: ' Nearest expiry: {date}.'
    },
    fr: {
      one: 'Vous avez 1 bon valide.',
      many: 'Vous avez {n} bons valides.',
      soonest: ' Expiration la plus proche : {date}.'
    }
  };

  function messageFor(lang, count, soonest) {
    const dict = MESSAGES[lang] || MESSAGES.en;
    let text = count === 1 ? dict.one : dict.many.split('{n}').join(count);
    if (soonest) {
      text += dict.soonest.split('{date}').join(soonest);
    }
    return text;
  }

  // Same language resolution as the popup (settings + browser locale)
  function resolveLanguage(setting) {
    if (setting === 'en' || setting === 'fr') return setting;
    return ((navigator.language || 'en').toLowerCase().indexOf('fr') === 0)
        ? 'fr' : 'en';
  }

  function isSncfUrl(url) {
    try {
      const parsed = new URL(url);
      return parsed.protocol.indexOf('http') === 0 &&
             SNCF_HOST_RE.test(parsed.hostname);
    } catch (e) {
      return false;
    }
  }

  // Fire the notification for a tab that just finished loading the site
  async function notifyArrival(tabId) {
    try {
      const data = await browser.storage.local.get('settings');
      const settings = data.settings || {};
      if (settings.notifications === false) {
        return; // the notifications toggle in Settings is off
      }

      const valid = await getValidVouchers(); // from background.js
      if (valid.length === 0) {
        return;
      }

      notifiedTabs.add(tabId);

      // Oldest-first sort from getValidVouchers: the first expiry is
      // the nearest one
      const soonest = valid[0].expiryDate;
      const lang = resolveLanguage(settings.language);
      let iconUrl = 'icons/icon-128.png';
      if (browser.runtime && browser.runtime.getURL) {
        iconUrl = browser.runtime.getURL('icons/icon-128.png');
      }

      await browser.notifications.create({
        type: 'basic',
        iconUrl: iconUrl,
        title: 'wagonBar',
        message: messageFor(lang, valid.length, soonest)
      });
    } catch (e) {
      console.log('wagonBar: arrival notification failed:', e);
    }
  }

  browser.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
    if (changeInfo.status !== 'complete') return;
    const url = (tab && tab.url) || changeInfo.url || '';
    if (!isSncfUrl(url)) {
      notifiedTabs.delete(tabId); // left the site: next visit notifies again
      return;
    }
    if (notifiedTabs.has(tabId)) return; // already notified this visit
    notifyArrival(tabId);
  });

  browser.tabs.onRemoved.addListener(function (tabId) {
    notifiedTabs.delete(tabId);
  });

  // A click just dismisses the notification (an extension popup cannot
  // be opened programmatically; the toolbar badge already shows the count)
  if (browser.notifications.onClicked) {
    browser.notifications.onClicked.addListener(function (id) {
      browser.notifications.clear(id);
    });
  }
})();
