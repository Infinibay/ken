"""Transactional up/down, rejecting foreign databases and future schemas."""
from __future__ import annotations

import sqlite3

from .schema import APPLICATION_ID, CHECKSUMS, DOWN, MIGRATIONS, TABLES_BY_VERSION, VERSION


class StoreFormatError(ValueError):
    pass


def validate(db: sqlite3.Connection, *, allow_empty: bool = False) -> int:
    app = db.execute('PRAGMA application_id').fetchone()[0]
    version = db.execute('PRAGMA user_version').fetchone()[0]
    objects = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if not objects and app in (0, APPLICATION_ID) and version == 0 and allow_empty:
        return 0
    if app != APPLICATION_ID or version not in MIGRATIONS or objects != set(TABLES_BY_VERSION[version]):
        raise StoreFormatError('unrecognized structural store ownership or schema; no changes made')
    ledger = dict(db.execute('SELECT version,checksum FROM k2_migrations'))
    if ledger != {v: CHECKSUMS[v] for v in range(1,version+1)}:
        raise StoreFormatError('migration checksum mismatch')
    # The ledger alone cannot vouch for externally modified DDL.
    expected = sqlite3.connect(':memory:')
    try:
        for step in range(1,version+1):
            for sql in MIGRATIONS[step]:
                expected.execute(sql)
        schema_sql = "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        if db.execute(schema_sql).fetchall() != expected.execute(schema_sql).fetchall():
            raise StoreFormatError('schema differs from the migration manifest')
    finally:
        expected.close()
    return version


def migrate(db: sqlite3.Connection, target: int = VERSION) -> None:
    if target not in (0, *MIGRATIONS):
        raise StoreFormatError('unsupported migration target')
    db.execute('BEGIN IMMEDIATE')
    try:
        current = validate(db, allow_empty=True)
        if current < target:
            for step in range(current+1,target+1):
                for sql in MIGRATIONS[step]:
                    db.execute(sql)
                db.execute('INSERT INTO k2_migrations VALUES (?,?)', (step,CHECKSUMS[step]))
                db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                db.execute(f'PRAGMA user_version={step}')
        elif current > target:
            for step in range(current,target,-1):
                for sql in DOWN[step]:
                    db.execute(sql)
                if step > 1:
                    db.execute('DELETE FROM k2_migrations WHERE version=?',(step,))
                db.execute(f'PRAGMA user_version={step-1}')
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise
