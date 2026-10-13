// Shared helpers for the cross-device voucher sync layer.
//
// storage.local is the durable source of truth; storage.sync (where the
// browser provides it) replicates vouchers across devices signed into
// the same browser account (Firefox account / Google account). The
// popup pushes user actions here; background/sync.js merges remote
// changes back into local storage. Safari has no storage.sync: these
// helpers degrade to no-ops and the extension keeps working locally.

// Sync keys are per-voucher ("voucher-<id>") so concurrent writes from
// different devices never clobber each other's vouchers
const SYNC_PREFIX = 'voucher-';
// Deletes are tombstones so a device that was offline at deletion time
// cannot resurrect the voucher; old tombstones are pruned by the
// background reconcile
const TOMBSTONE_MAX_AGE_MS = 90 * 24 * 60 * 60 * 1000;

function syncKeyFor(id) {
  return SYNC_PREFIX + id;
}

function getSyncArea() {
  return (typeof browser !== 'undefined' && browser.storage &&
          browser.storage.sync) ? browser.storage.sync : null;
}

// Stable per-device identifier used to ignore our own writes coming
// back through storage.sync change events
async function getDeviceId() {
  const data = await browser.storage.local.get('deviceId');
  if (data.deviceId) {
    return data.deviceId;
  }
  const deviceId = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : String(Date.now()) + Math.random();
  await browser.storage.local.set({ deviceId: deviceId });
  return deviceId;
}

// Push one voucher (or its deletion) to the sync area. The record
// carries updatedAt + the writing device's id: remote merges are
// last-write-wins per voucher, and echoes of our own writes are
// ignored. No-op when the browser has no storage.sync.
async function syncWriteVoucher(voucher, deleted) {
  const sync = getSyncArea();
  if (!sync) {
    return;
  }
  try {
    const by = await getDeviceId();
    const record = deleted
        ? { deleted: true, updatedAt: new Date().toISOString(), by: by }
        : Object.assign({}, voucher,
                        { updatedAt: new Date().toISOString(), by: by });
    const item = {};
    item[syncKeyFor(voucher.id)] = record;
    await sync.set(item);
  } catch (e) {
    // sync quota exceeded or the area is unavailable: local storage
    // already has the change, so this is not fatal
    console.log('wagonBAR: voucher sync failed:', e);
  }
}
