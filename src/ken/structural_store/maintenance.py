"""Quota-pressure reclamation without invalidating leased source snapshots."""
from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING
from .leases import renew

if TYPE_CHECKING:
    from .store import Store


def trim(store: Store, *, pressure: bool = False) -> dict[str,int | bool]:
    """Discard unpinned retained data and compact only under quota pressure.

    A building lease in another process protects its unpublished units. A reader
    lease protects snapshot membership and its analysis. Staged units in this
    Store are protected independently. If these exceed the quota, leave them
    intact; the caller can use ephemeral storage for subsequent acquisitions.
    """
    before = store.allocated_bytes
    result: dict[str,int | bool] = {'before_bytes':before,'after_bytes':before,
                                  'deferred':False,'snapshots':0,'units':0}
    if store.path is None or store.limit_bytes is None or (before <= store.limit_bytes and not pressure):
        return result
    renew(store,force=True)
    with store.transaction(reclamation=True):
        store.db.execute('DELETE FROM k2_leases WHERE expires_ns<=?',(time.time_ns(),))
        if store.db.execute('SELECT 1 FROM k2_leases WHERE snapshot_id IS NULL AND lease_id!=? LIMIT 1',
                            (store.lease_id or '',)).fetchone():
            result['deferred'] = True
            return result
        # Compiled plans/results are disposable; source facts of active readers
        # are not. Deleting an artifact does not affect an already-loaded plan.
        store.db.execute('DELETE FROM k2_artifacts')
        removed = store.db.execute('''DELETE FROM k2_snapshots WHERE NOT EXISTS
            (SELECT 1 FROM k2_leases l WHERE l.snapshot_id=k2_snapshots.snapshot_id)''').rowcount
        result['snapshots'] = removed
        current = store.current
        if current is not None and not store.db.execute('SELECT 1 FROM k2_snapshots WHERE snapshot_id=?',(current,)).fetchone():
            store.db.execute("DELETE FROM k2_meta WHERE key='published'")
        unused = [r[0] for r in store.db.execute('''SELECT unit_id FROM k2_units u WHERE NOT EXISTS
            (SELECT 1 FROM k2_snapshot_units m WHERE m.unit_id=u.unit_id)''') if r[0] not in store.staged_units]
        store.db.executemany('DELETE FROM k2_units WHERE unit_id=?',((u,) for u in unused))
        result['units'] = len(unused)
    # Admission pressure needs reusable pages, not a full file rewrite. If the
    # file itself fits, SQLite can reuse its freelist for the next unit.
    if before <= store.limit_bytes or not store.db.execute('PRAGMA freelist_count').fetchone()[0]:
        result['after_bytes'] = store.allocated_bytes
        return result
    # VACUUM changes layout, not logical identities. A concurrent reader may
    # defer compaction, but cannot make us discard its leased facts above.
    try:
        store.db.execute('VACUUM')
        store.db.execute('PRAGMA wal_checkpoint(PASSIVE)')
    except sqlite3.OperationalError as exc:
        if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
            raise
        result['deferred'] = True
    result['after_bytes'] = store.allocated_bytes
    return result
