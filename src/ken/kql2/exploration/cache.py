"""Atomic per-file syntax publication and grouped candidate indexes.

SQL is restricted to cache publication, metadata and candidate roots. Every
predicate and structural navigation runs over FlatBuffers vectors in Python.
Readers hold a SQLite snapshot; changing a file cannot mix old trees/new IDs.
"""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

import numpy as np

from .storage_codec import Dictionary, encode_flat, validate

VERSION = 1
SCHEMA = (
    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TABLE words(id INTEGER PRIMARY KEY,word TEXT UNIQUE NOT NULL)",
    "CREATE TABLE units(id INTEGER PRIMARY KEY,path TEXT UNIQUE NOT NULL,language TEXT NOT NULL,source_hash TEXT NOT NULL,frontend TEXT NOT NULL,source BLOB NOT NULL,ast BLOB NOT NULL,ast_hash TEXT NOT NULL,errors INTEGER NOT NULL)",
    "CREATE TABLE postings(kind INTEGER,unit INTEGER REFERENCES units ON DELETE CASCADE,nodes BLOB NOT NULL,PRIMARY KEY(kind,unit)) WITHOUT ROWID",
    "CREATE INDEX postings_unit ON postings(unit)",
)


class SyntaxCache:
    def __init__(self, path: Path | None, root: Path):
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path or ":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA cache_size=-16384")
        self.db.execute("PRAGMA journal_mode=WAL")
        # This is a derived cache. WAL keeps publication atomic; NORMAL avoids
        # fsync per source file. A power loss may discard recent cache entries,
        # which are rebuilt from source hashes on the next acquisition.
        self.db.execute("PRAGMA synchronous=NORMAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, VERSION):
            self.close()
            raise ValueError(f"unsupported syntax cache schema {version}")
        with self.db:
            if version == 0:
                self.db.execute("BEGIN IMMEDIATE")
                for sql in SCHEMA:
                    self.db.execute(sql)
                self.db.execute(f"PRAGMA user_version={VERSION}")
                self.db.execute("INSERT INTO metadata VALUES ('root',?)", (str(root),))
                self.db.execute("INSERT INTO words VALUES (0,'')")
        found = self.db.execute(
            "SELECT value FROM metadata WHERE key='root'"
        ).fetchone()
        if found != (str(root),):
            self.close()
            raise ValueError("syntax cache belongs to a different source root")
        self.dictionary = Dictionary()
        self.dictionary.words = [
            r[0] for r in self.db.execute("SELECT word FROM words ORDER BY id")
        ]
        self.dictionary.ids = {word: i for i, word in enumerate(self.dictionary.words)}
        self.saved_words = len(self.dictionary.words)
        self.views: OrderedDict[int, object] = OrderedDict()
        self.units: dict[int, tuple[str, str, str, int]] = {}
        self.scanned = 0

    def find(self, path, source_hash, frontend):
        return self.db.execute(
            "SELECT id,errors FROM units WHERE path=? AND source_hash=? AND frontend=?",
            (path, source_hash, frontend),
        ).fetchone()

    def put(self, path, language, source_hash, frontend, source, columns):
        blob = encode_flat(columns)
        ids = np.flatnonzero(columns[6] & 1).astype("<u4")
        kinds = columns[0][ids]
        order = np.argsort(kinds, kind="stable")
        ids, kinds = ids[order], kinds[order]
        boundaries = np.flatnonzero(np.r_[True, kinds[1:] != kinds[:-1], True])
        errors = int(bool(columns[6][0] & 2))
        with self.db:
            self.db.executemany(
                "INSERT INTO words VALUES (?,?)",
                enumerate(self.dictionary.words[self.saved_words :], self.saved_words),
            )
            # Preserve unit identity while atomically replacing content and postings.
            row = self.db.execute(
                "SELECT id FROM units WHERE path=?", (path,)
            ).fetchone()
            unit = row[0] if row else None
            if unit is not None:
                self.db.execute("DELETE FROM postings WHERE unit=?", (unit,))
            cursor = self.db.execute(
                "INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    unit,
                    path,
                    language,
                    source_hash,
                    frontend,
                    source,
                    blob,
                    sha256(blob).hexdigest(),
                    errors,
                ),
            )
            unit = unit if unit is not None else cursor.lastrowid
            self.db.executemany(
                "INSERT INTO postings VALUES (?,?,?)",
                (
                    (int(kinds[a]), unit, ids[a:b].tobytes())
                    for a, b in pairwise(boundaries)
                    if b > a
                ),
            )
        self.saved_words = len(self.dictionary.words)
        return unit, errors

    def snapshot(self, selected, *, scope=None):
        self.db.execute("CREATE TEMP TABLE selected(unit INTEGER PRIMARY KEY)")
        self.db.executemany("INSERT INTO selected VALUES (?)", ((u,) for u in selected))
        if scope is not None:
            # Only reconcile the acquired scope: a partial search must never
            # evict unrelated files. Missing/ignored/unreadable revisions leave
            # no obsolete source text behind after a successful acquisition.
            prefix = scope.rstrip("/") + "/" if scope else ""
            self.db.execute(
                "DELETE FROM units WHERE id NOT IN (SELECT unit FROM selected) "
                "AND (?='' OR path=? OR substr(path,1,length(?))=?)",
                (scope, scope, prefix, prefix),
            )
        self.db.commit()
        self.db.execute("BEGIN")
        self.units = {
            unit: (path, language, source_hash, errors)
            for unit, path, language, source_hash, errors in self.db.execute(
                "SELECT id,path,language,source_hash,errors FROM units JOIN selected ON id=unit ORDER BY path"
            )
        }

    def view(self, unit):
        from .tree import SyntaxTree

        found = self.views.get(unit)
        if found is None:
            source, blob, digest = self.db.execute(
                "SELECT source,ast,ast_hash FROM units WHERE id=?", (unit,)
            ).fetchone()
            if sha256(blob).hexdigest() != digest:
                raise ValueError("corrupt syntax cache: AST checksum mismatch")
            columns = validate(blob, len(source), len(self.dictionary.words))
            path, language, source_hash, _errors = self.units[unit]
            found = SyntaxTree(
                unit, path, language, source_hash, source, columns, self.dictionary
            )
            self.views[unit] = found
            while len(self.views) > 2:
                self.views.popitem(last=False)
        self.views.move_to_end(unit)
        return found

    def candidates(self, kinds, *, unit=None):
        """One indexed posting-list read, not a SQL query per matched node."""
        if kinds is not None and not kinds:
            return
        sql = "SELECT p.unit,p.nodes FROM postings p JOIN selected s ON s.unit=p.unit"
        terms, params = [], []
        if kinds is not None:
            terms.append("p.kind IN (" + ",".join("?" for _ in kinds) + ")")
            params.extend(sorted(kinds))
        if unit is not None:
            terms.append("p.unit=?")
            params.append(unit)
        sql += (" WHERE " + " AND ".join(terms)) if terms else ""
        sql += " ORDER BY p.unit,p.kind"
        current, lists = None, []
        for owner, payload in self.db.execute(sql, params):
            if len(payload) % 4:
                raise ValueError("corrupt syntax posting list")
            if current is not None and current != owner:
                yield current, np.sort(np.concatenate(lists))
                lists = []
            current = owner
            lists.append(np.frombuffer(payload, dtype="<u4"))
        if current is not None:
            yield current, np.sort(np.concatenate(lists))

    @property
    def allocated_bytes(self):
        return (
            self.db.execute("PRAGMA page_count").fetchone()[0]
            * self.db.execute("PRAGMA page_size").fetchone()[0]
        )

    def close(self):
        if hasattr(self, "views"):
            self.views.clear()
        self.db.close()

    def trim(self, budget_bytes):
        """Enforce retained-cache capacity after readers release their snapshot.

        The working set may exceed retention while a complete query runs.
        Concurrent readers can delay physical reclamation of WAL pages.
        """
        self.db.rollback()
        self.views.clear()
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        evicted = 0
        while True:
            used = (
                self.allocated_bytes
                - page_size * self.db.execute("PRAGMA freelist_count").fetchone()[0]
            )
            if used <= budget_bytes:
                break
            victims = self.db.execute(
                "SELECT id FROM units ORDER BY id LIMIT 16"
            ).fetchall()
            if not victims:
                break
            with self.db:
                self.db.executemany("DELETE FROM units WHERE id=?", victims)
            evicted += len(victims)
        if evicted:
            self.db.execute("VACUUM")
        return evicted
