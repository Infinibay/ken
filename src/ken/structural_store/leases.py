"""Process-independent leases and conservative snapshot collection."""
from __future__ import annotations

import time
from uuid import uuid4
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store

TTL_NS = 300_000_000_000


class SnapshotExpired(RuntimeError):
    pass


def create(store: Store) -> str:
    token = uuid4().hex
    store.db.execute('INSERT INTO k2_leases VALUES (?,NULL,?)', (token,time.time_ns()+TTL_NS))
    return token


def renew(store: Store, *, force: bool = False) -> None:
    if store.lease_id is None or not force and time.monotonic() < store.lease_renew_at:
        return
    now = time.time_ns()
    updated = store.db.execute('UPDATE k2_leases SET expires_ns=? WHERE lease_id=? AND expires_ns>?',
                               (now+TTL_NS,store.lease_id,now))
    if updated.rowcount != 1:
        raise SnapshotExpired('snapshot lease expired; restart acquisition')
    store.lease_renew_at = time.monotonic()+15


def pin(store: Store, snapshot: int) -> None:
    if store.lease_id is None:
        return
    renew(store,force=True)
    store.db.execute('UPDATE k2_leases SET snapshot_id=? WHERE lease_id=?',(snapshot,store.lease_id))


def collect(store: Store, *, retain: int = 2, protected_units: tuple[int,...] = ()) -> dict[str,int | bool]:
    """Never evict an active snapshot or collect during another acquisition.

    Deletion frees SQLite pages for reuse. Compaction is a separate, explicit
    maintenance operation; GC does not rewrite a large database per request.
    """
    if retain < 1:
        raise ValueError('retain must be at least one snapshot')
    renew(store,force=True)
    with store.transaction(reclamation=True):
        store.db.execute('DELETE FROM k2_leases WHERE expires_ns<=?', (time.time_ns(),))
        building = store.db.execute('SELECT 1 FROM k2_leases WHERE snapshot_id IS NULL AND lease_id!=? LIMIT 1',
                                    (store.lease_id or '',)).fetchone()
        if building:
            return {'deferred':True,'snapshots':0,'units':0}
        keep = {row[0] for row in store.db.execute('SELECT snapshot_id FROM k2_snapshots ORDER BY snapshot_id DESC LIMIT ?', (retain,))}
        keep.update(row[0] for row in store.db.execute('SELECT snapshot_id FROM k2_leases WHERE snapshot_id IS NOT NULL'))
        if store.current is not None:
            keep.add(store.current)
        old = [row[0] for row in store.db.execute('SELECT snapshot_id FROM k2_snapshots') if row[0] not in keep]
        store.db.executemany('DELETE FROM k2_snapshots WHERE snapshot_id=?', ((s,) for s in old))
        protected = set(protected_units) | store.staged_units
        unused = [row[0] for row in store.db.execute('''SELECT u.unit_id FROM k2_units u
                  WHERE NOT EXISTS (SELECT 1 FROM k2_snapshot_units m WHERE m.unit_id=u.unit_id)''')
                  if row[0] not in protected]
        store.db.executemany('DELETE FROM k2_units WHERE unit_id=?', ((u,) for u in unused))
        return {'deferred':False,'snapshots':len(old),'units':len(unused)}
