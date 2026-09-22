"""Indexed source-unit store; snapshot membership is required on every node scan.

This bootstrap stores source facts losslessly. It does not claim KQL2 semantic
coverage for legacy facts. Global analysis segments are a separate future stage.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3
from typing import Callable, Iterator
import zlib
import time

from ken.structural.model import IR
from .migrations import migrate, validate

Scalar = str | int | float | bool | None
MIN_PERSISTENT_MB = 0.512


def scalar(value: Scalar) -> tuple[str, str]:
    tag = {str: 'String', int: 'Int', float: 'Float', bool: 'Bool', type(None): 'Null'}.get(type(value))
    if tag is None or isinstance(value, float) and not math.isfinite(value):
        raise ValueError('unsupported scalar')
    return tag, json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def native_scalar(value: Scalar) -> tuple[str, Scalar]:
    tag = {str: 'String', int: 'Int', float: 'Float', bool: 'Bool', type(None): 'Null'}.get(type(value))
    if tag is None or isinstance(value, float) and not math.isfinite(value):
        raise ValueError('unsupported scalar')
    if type(value) is int and not -(2**63) <= value < 2**63:
        return tag, str(value)
    if type(value) is float and value == 0 and math.copysign(1, value) < 0:
        return tag, '-0.0'
    return tag, value


def fingerprint(*parts: str) -> str:
    digest = sha256()
    for part in parts:
        raw = part.encode()
        digest.update(len(raw).to_bytes(8, 'big'))
        digest.update(raw)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Node:
    id: int
    unit: int
    local_id: str
    kind: str
    name: str | None
    owner: str | None
    line: int
    end_line: int
    path: str
    language: str


class Store:
    def __init__(self, path: Path | None = None, *, cache_mb: float | None = 500):
        if cache_mb is not None and (not math.isfinite(cache_mb) or cache_mb < 0):
            raise ValueError('cache_mb must be finite and nonnegative')
        # Below the schema overhead, use work storage rather than exceed retention.
        # None is explicit persistent-index storage, rather than a size-bounded
        # disposable cache. A source index may exceed the 500 MB artifact cache.
        self.path = path if cache_mb is None or cache_mb >= MIN_PERSISTENT_MB else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # Empty filename is an ephemeral on-disk SQLite DB; avoids forcing a
        # project into RAM when retention is disabled.
        self.db = sqlite3.connect(str(self.path) if self.path else '', isolation_level=None)
        self.scanned = 0
        self.lease_id: str | None = None
        self.lease_renew_at = 0.0
        self.staged_units: set[int] = set()
        try:
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA busy_timeout=5000')
            # Keep upper B-tree levels and hot leaf pages during bulk indexing.
            # SQLite's ~2 MB default churns dirty WAL pages on million-node
            # graphs. This is a bounded page cache, independent of disk retention.
            self.db.execute('PRAGMA cache_size=-65536')
            validate(self.db, allow_empty=True)
            if self.path:
                self.db.execute('PRAGMA journal_mode=WAL')
            migrate(self.db)
            self.limit_bytes: int | None = int(cache_mb * 1_000_000) if self.path and cache_mb is not None else None
            if self.path:
                from .leases import create
                self.lease_id = create(self)
                self.lease_renew_at = time.monotonic()+15
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        if self.lease_id is not None and self.db.execute('PRAGMA user_version').fetchone()[0] >= 3:
            self.db.execute('DELETE FROM k2_leases WHERE lease_id=?',(self.lease_id,))
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def allocated_bytes(self) -> int:
        return self.db.execute('PRAGMA page_count').fetchone()[0] * self.db.execute('PRAGMA page_size').fetchone()[0]

    @contextmanager
    def transaction(self, *, reclamation: bool = False, retry_busy: Callable[[], None] | None = None) -> Iterator[None]:
        # Retry only lock acquisition: replaying a transaction body could repeat
        # consumed input or externally visible work. SQLite's busy timeout waits
        # between callbacks; callers retain their cancellation/deadline policy.
        while True:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                break
            except sqlite3.OperationalError as error:
                if retry_busy is None or getattr(error, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY:
                    raise
                retry_busy()
        try:
            yield
            if not reclamation and self.limit_bytes is not None and self.allocated_bytes > self.limit_bytes:
                raise MemoryError('structural retention budget exceeded; use an ephemeral store')
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def find_unit(self, key: str) -> int | None:
        from .leases import renew
        renew(self)
        if self.lease_id is not None:
            lease = self.db.execute('SELECT snapshot_id FROM k2_leases WHERE lease_id=?',(self.lease_id,)).fetchone()
            if lease is not None and lease[0] is not None:
                self.db.execute('UPDATE k2_leases SET snapshot_id=NULL WHERE lease_id=?',(self.lease_id,))
        row = self.db.execute('SELECT unit_id FROM k2_units WHERE unit_key=?', (key,)).fetchone()
        if row:
            self.staged_units.add(row[0])
        return row[0] if row else None

    def load_unit(self, unit: int) -> IR:
        row = self.db.execute('SELECT payload FROM k2_units WHERE unit_id=?', (unit,)).fetchone()
        if row is None:
            raise KeyError(unit)
        return IR.from_dict(json.loads(zlib.decompress(row[0])))

    def put_unit(self, key: str, ir: IR, source_hash: str, frontend_hash: str) -> int:
        with self.transaction():
            existing = self.find_unit(key)
            if existing is not None:
                return existing
            payload = zlib.compress(json.dumps(ir.to_dict(), sort_keys=True).encode())
            result = self.db.execute('INSERT INTO k2_units(unit_key,path,language,source_hash,frontend_hash,payload,coverage) VALUES (?,?,?,?,?,?,?)',
                                     (key, ir.path, ir.language, source_hash, frontend_hash, payload, int(not ir.diagnostics)))
            assert result.lastrowid is not None
            unit = result.lastrowid
            self.staged_units.add(unit)
            # Immediate ownership as stored: a member's ``owner`` is the declaring
            # type or callable. Calls are owned by the callable whose body holds
            # them, which is what an owner-scoped ``call`` selector scans for.
            owners = {f.object: f.subject for f in ir.facts
                      if f.relation in {'HAS_METHOD', 'HAS_FIELD', 'HAS_PARAMETER', 'HAS_CALL', 'DECLARES'}}
            fields = {f.object for f in ir.facts if f.relation == 'HAS_FIELD'}
            for entity in ir.entities.values():
                owner = owners.get(entity.id)
                kind = 'FIELD' if entity.id in fields and entity.kind == 'STORAGE' else entity.kind
                self.db.execute('INSERT INTO k2_nodes(unit_id,local_id,kind,name,owner,line,end_line) VALUES (?,?,?,?,?,?,?)',
                                (unit, entity.id, kind, entity.name, owner, entity.line, entity.end_line))
            ids = dict(self.db.execute('SELECT local_id,node_id FROM k2_nodes WHERE unit_id=?', (unit,)))
            parameter_facts = {f.object: f.attrs for f in ir.facts if f.relation == 'HAS_PARAMETER'}
            properties = []
            for entity in ir.entities.values():
                attrs = dict(entity.attrs)
                if 'async_' in attrs:
                    attrs['async'] = attrs.pop('async_')
                if entity.kind == 'PARAMETER':
                    attrs['native_position'] = attrs.get('position')
                    attrs.update({k: v for k, v in parameter_facts.get(entity.id, {}).items() if k in ('position', 'receiver')})
                    if attrs.get('receiver'):
                        attrs.pop('position', None)
                for name, value in attrs.items():
                    if type(value) in (str, int, bool, float, type(None)):
                        try:
                            tag, encoded = native_scalar(value)
                        except ValueError:
                            continue
                        properties.append((ids[entity.id], name, tag, encoded))
            self.db.executemany('INSERT INTO k2_properties VALUES (?,?,?,?)', properties)
            self.db.executemany('INSERT INTO k2_facts VALUES (?,?,?,?,?,?,?)',
                                ((unit, i, f.subject, f.relation, f.object, json.dumps(f.attrs, sort_keys=True), json.dumps(f.evidence)) for i, f in enumerate(ir.facts)))
            from .operations import project
            project(self,unit,ir)
            from ken.common_ast import normalize
            from .common_ast import project as project_ast
            project_ast(self,unit,normalize(ir))
            return unit

    @property
    def current(self) -> int | None:
        row = self.db.execute("SELECT value FROM k2_meta WHERE key='published'").fetchone()
        return int(row[0]) if row else None

    def publish(self, units: list[int], *, expected_parent: int | None, profile: str = 'legacy-source/1', complete: bool = True) -> int:
        if len(set(units)) != len(units):
            raise ValueError('duplicate unit')
        with self.transaction():
            if self.current != expected_parent:
                raise ValueError('snapshot publication conflict')
            members = []
            for unit in units:
                row = self.db.execute('SELECT path,unit_key,coverage FROM k2_units WHERE unit_id=?', (unit,)).fetchone()
                if row is None:
                    raise KeyError(unit)
                members.append((row[0], row[1], unit))
                complete &= bool(row[2])
            if len({path for path, _, _ in members}) != len(members):
                raise ValueError('two revisions of one path in a snapshot')
            members.sort()
            manifest = fingerprint(profile, str(complete), *(key for _, key, _ in members))
            found = self.db.execute('SELECT snapshot_id FROM k2_snapshots WHERE manifest=?', (manifest,)).fetchone()
            if found:
                snapshot = found[0]
            else:
                result = self.db.execute('INSERT INTO k2_snapshots(manifest,profile,coverage) VALUES (?,?,?)', (manifest, profile, int(complete)))
                assert result.lastrowid is not None
                snapshot = result.lastrowid
                self.db.executemany('INSERT INTO k2_snapshot_units VALUES (?,?,?)', ((snapshot, unit, path) for path, _, unit in members))
            self.db.execute("INSERT INTO k2_meta VALUES ('published',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(snapshot),))
            from .leases import pin
            pin(self,snapshot)
            return snapshot

    def scan(self, snapshot: int, *, kind: str | None = None, name: str | None = None, owner: Node | None = None, node_id: int | None = None, reference: bool = False) -> Iterator[Node]:
        sql, params = self.scan_sql(snapshot, kind=kind, name=name, owner=owner, node_id=node_id, reference=reference)
        for row in self.db.execute(sql, params):
            self.scanned += 1
            node = Node(*row)
            if (kind is None or node.kind == kind) and (name is None or node.name is None or node.name == name) and (owner is None or node.unit == owner.unit and node.owner == owner.local_id) and (node_id is None or node.id == node_id):
                yield node

    def scan_sql(self, snapshot: int, *, kind: str | None = None, name: str | None = None, owner: Node | None = None, node_id: int | None = None, reference: bool = False) -> tuple[str, list[Scalar]]:
        if not self.db.execute('SELECT 1 FROM k2_snapshots WHERE snapshot_id=?', (snapshot,)).fetchone():
            raise KeyError(snapshot)
        sql = '''SELECT n.node_id,n.unit_id,n.local_id,n.kind,n.name,n.owner,n.line,n.end_line,u.path,u.language
                 FROM k2_nodes n JOIN k2_units u ON u.unit_id=n.unit_id
                 JOIN k2_snapshot_units m ON m.unit_id=n.unit_id WHERE m.snapshot_id=?'''
        params: list[Scalar] = [snapshot]
        if not reference:
            for column, value in (('n.kind', kind), ('n.node_id', node_id)):
                if value is not None:
                    sql += f' AND {column}=?'
                    params.append(value)
            if owner is not None:
                sql += ' AND n.unit_id=? AND n.owner=?'
                params += [owner.unit, owner.local_id]
            if name is not None:
                # Disjoint indexed probes preserve unknown names without an OR
                # that makes SQLite scan every node of this kind.
                sql = sql + ' AND n.name=? UNION ALL ' + sql + ' AND n.name IS NULL'
                params = params + [name] + params
        return sql, params

    def properties(self, node: Node) -> dict[str, Scalar]:
        result: dict[str, Scalar] = {
            key: bool(value) if tag == 'Bool' else int(value) if tag == 'Int' else float(value) if tag == 'Float' else value
            for key, tag, value in self.db.execute('SELECT key,tag,value FROM k2_properties WHERE node_id=?', (node.id,))}
        result.update(name=node.name, path=node.path, language=node.language)
        return result
