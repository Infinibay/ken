"""Checksummed disk artifacts. No pickle, arbitrary class loading or timestamps per hit."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import time

from .migrations import validate
from .store import Store


def read_existing(path: Path, key: str, codec: str, *, max_bytes: int) -> bytes | None:
    if not path.is_file() or max_bytes <= 0:
        return None
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    try:
        # Another process may have created the file without committing its
        # first migration yet. Read one consistent snapshot and treat a wholly
        # empty, unclaimed store as a cache miss; foreign schemas still fail.
        db.execute('BEGIN')
        version=validate(db,allow_empty=True)
        if version < 2:
            return None
        return read(db,key,codec,max_bytes=max_bytes)
    finally:
        db.close()


def read(db: sqlite3.Connection, key: str, codec: str, *, max_bytes: int) -> bytes | None:
    row=db.execute('SELECT checksum,payload FROM k2_artifacts WHERE artifact_key=? AND codec=? AND bytes<=?',(key,codec,max_bytes)).fetchone()
    if row is None:
        return None
    checksum,payload=row
    if len(payload)>max_bytes or sha256(payload).hexdigest()!=checksum:
        return None
    return payload


def write(store: Store, key: str, kind: str, codec: str, payload: bytes, *, snapshot: int | None = None) -> bool:
    if store.path is None or store.limit_bytes is None or len(payload)>store.limit_bytes//5:
        return False
    try:
        with store.transaction():
            # Artifacts are expendable. Source-unit/snapshot rows are never
            # removed here; graph GC has stronger reader/pin requirements.
            existing=store.db.execute('SELECT coalesce(sum(bytes),0) FROM k2_artifacts WHERE artifact_key<>?',(key,)).fetchone()[0]
            allowance=max(0,store.limit_bytes//5)
            while existing+len(payload)>allowance:
                oldest=store.db.execute('SELECT artifact_key,bytes FROM k2_artifacts WHERE artifact_key<>? ORDER BY touched LIMIT 1',(key,)).fetchone()
                if oldest is None:
                    return False
                store.db.execute('DELETE FROM k2_artifacts WHERE artifact_key=?',(oldest[0],))
                existing-=oldest[1]
            store.db.execute('''INSERT INTO k2_artifacts VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(artifact_key) DO UPDATE SET kind=excluded.kind,codec=excluded.codec,
                checksum=excluded.checksum,payload=excluded.payload,snapshot_id=excluded.snapshot_id,
                touched=excluded.touched,bytes=excluded.bytes''',
                (key,kind,codec,sha256(payload).hexdigest(),payload,snapshot,time.time_ns(),len(payload)))
        return True
    except MemoryError:
        return False


def touch_many(store: Store, keys: set[str]) -> None:
    """One request-boundary write for all hits; no write transaction per lookup."""
    if not keys or store.path is None:
        return
    try:
        with store.transaction():
            store.db.executemany('UPDATE k2_artifacts SET touched=? WHERE artifact_key=?',((time.time_ns(),key) for key in keys))
    except MemoryError:
        pass
