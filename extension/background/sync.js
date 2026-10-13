// Cross-device voucher sync, background side. The popup pushes user
// actions to the sync area (syncWriteVoucher in shared/sync-common.js);
// this script merges remote changes back into local storage and
// reconciles both sides once per background start.
//
// Conflict policy, per voucher:
// - last write wins, by updatedAt timestamp
// - deletes are tombstones ({deleted: true, updatedAt, by}), so a
//   device offline at deletion time cannot resurrect the voucher
// - our own writes coming back through sync events are ignored (by)
//
// Firefox keeps no durable local mirror for the sync area until an
// account is configured, so storage.local always stays the source of
// truth and the sync area is only ever a copy.

(function () {
  const sync = getSyncArea();
  if (!sync) {
    return; // no storage.sync (Safari): the extension is local-only
  }

  // Last-known modification time of a voucher record
  function timeOf(voucher) {
    return Date.parse(voucher.updatedAt || voucher.createdAt || 0) || 0;
  }

  // Merge remote sync changes into the local voucher list
  async function applyRemote(changes) {
    const by = await getDeviceId();
    const data = await browser.storage.local.get('vouchers');
    const vouchers = (data.vouchers || []).slice();
    let changed = false;

    Object.keys(changes).forEach(function (key) {
      if (key.indexOf(SYNC_PREFIX) !== 0) {
        return;
      }
      const remote = changes[key].newValue;
      if (!remote || remote.by === by) {
        return; // key removed remotely or our own write echoing back
      }
      const id = key.slice(SYNC_PREFIX.length);
      const idx = vouchers.findIndex(v => v.id === id);

      if (remote.deleted) {
        // never resurrect: only drop vouchers not re-created here since
        if (idx >= 0 && Date.parse(remote.updatedAt) > timeOf(vouchers[idx])) {
          vouchers.splice(idx, 1);
          changed = true;
        }
      } else if (idx < 0) {
        vouchers.push(remote);
        changed = true;
      } else if (Date.parse(remote.updatedAt) > timeOf(vouchers[idx])) {
        vouchers[idx] = remote;
        changed = true;
      }
    });

    if (changed) {
      // the local write triggers the badge update and the popup
      // re-render through their own storage.onChanged listeners
      await browser.storage.local.set({ vouchers: vouchers });
    }
  }

  // Startup reconciliation: take newer remote data into local, push
  // local-only vouchers up (pre-sync data, or creations from while the
  // sync area was unavailable), honour tombstones, prune tombstones
  // older than 90 days. This sync.get() also tells the Firefox sync
  // engine that this extension syncs: extensions that never touch the
  // sync area are skipped by it.
  async function reconcile() {
    const by = await getDeviceId();
    const data = await browser.storage.local.get('vouchers');
    const vouchers = (data.vouchers || []).slice();
    const remote = (await sync.get(null)) || {};
    let changed = false;
    const updates = {};
    const prune = [];

    Object.keys(remote).forEach(function (key) {
      if (key.indexOf(SYNC_PREFIX) !== 0) {
        return;
      }
      const r = remote[key];
      const id = key.slice(SYNC_PREFIX.length);
      const idx = vouchers.findIndex(v => v.id === id);

      if (r.deleted) {
        if (idx >= 0 && Date.parse(r.updatedAt) > timeOf(vouchers[idx])) {
          vouchers.splice(idx, 1);
          changed = true;
        }
        if (Date.now() - Date.parse(r.updatedAt) > TOMBSTONE_MAX_AGE_MS) {
          prune.push(key);
        }
      } else if (idx < 0) {
        // absent locally: restore it (even if we wrote it originally -
        // local storage may have been lost since)
        vouchers.push(r);
        changed = true;
      } else if (r.by !== by &&
                 Date.parse(r.updatedAt) > timeOf(vouchers[idx])) {
        vouchers[idx] = r;
        changed = true;
      }
    });

    vouchers.forEach(function (v) {
      const key = syncKeyFor(v.id);
      const r = remote[key];
      if (!r || (r.deleted && timeOf(v) > Date.parse(r.updatedAt))) {
        // never synced (migration / created while sync was unavailable),
        // or re-created here after a remote delete
        updates[key] = Object.assign({}, v, {
          updatedAt: new Date(timeOf(v) || Date.now()).toISOString(),
          by: by
        });
      }
    });

    if (changed) {
      await browser.storage.local.set({ vouchers: vouchers });
    }
    if (Object.keys(updates).length) {
      await sync.set(updates);
    }
    if (prune.length) {
      await sync.remove(prune);
    }
  }

  browser.storage.onChanged.addListener(function (changes, area) {
    if (area === 'sync') {
      applyRemote(changes).catch(
          e => console.log('wagonBAR: sync merge failed:', e));
    }
  });

  reconcile().catch(e => console.log('wagonBAR: sync reconcile failed:', e));
})();
