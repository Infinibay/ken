"""Hybrid catalog backend: compiled graph/CFG semantics over FlatBuffers buckets.

The semantic index remains authoritative for resolution and coverage. Repeated
fact joins and owner-operation walks use immutable vectors shared by the entire
catalog. This does not reinterpret semantic patterns as syntax-only predicates.
"""

import sqlite3
import time
from collections import OrderedDict
from collections.abc import Mapping
from contextlib import contextmanager
from hashlib import sha256

from ken.structural.model import FactIndex
from ken.structural_store.graph_records import StoredFact, StoredOperation

from .records import RecordRows, Records, encode

FACT_TEXT = frozenset((0, 1))
OP_TEXT = frozenset((0, 1, 2, 3, 4, 8))
MAX_BUCKET_ROWS = 100_000


class BucketCache:
    def __init__(
        self, path, revision, *, memory_bytes=64_000_000, disk_bytes=256_000_000
    ):
        self.revision, self.limit, self.disk_limit = revision, memory_bytes, disk_bytes
        self.memory, self.bytes = OrderedDict(), 0
        self.metrics = {
            "hits": 0,
            "disk_hits": 0,
            "builds": 0,
            "fallback": 0,
            "loaded_rows": 0,
            "build_ms": 0.0,
        }
        self.db = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS buckets(key TEXT PRIMARY KEY,revision TEXT NOT NULL,blob BLOB NOT NULL,digest TEXT NOT NULL)"
            )
            with self.db:
                self.db.execute("DELETE FROM buckets WHERE revision!=?", (revision,))

    def get(self, key, width, text_columns, produce, check):
        found = self.memory.get(key)
        if found is not None:
            self.memory.move_to_end(key)
            self.metrics["hits"] += 1
            return found
        check()
        disk_key = sha256(
            repr(("catalog-exploration/1", self.revision, key)).encode()
        ).hexdigest()
        row = (
            self.db.execute(
                "SELECT blob,digest FROM buckets WHERE key=?", (disk_key,)
            ).fetchone()
            if self.db
            else None
        )
        blob = None
        if row is not None and sha256(row[0]).hexdigest() == row[1]:
            blob = row[0]
            self.metrics["disk_hits"] += 1
        if blob is None:
            started = time.monotonic()
            blob = encode(produce(), width, text_columns, check)
            self.metrics["builds"] += 1
            self.metrics["build_ms"] += (time.monotonic() - started) * 1000
            if self.db is not None and len(blob) <= self.disk_limit:
                with self.db:
                    self.db.execute(
                        "INSERT OR REPLACE INTO buckets VALUES (?,?,?,?)",
                        (disk_key, self.revision, blob, sha256(blob).hexdigest()),
                    )
        found = Records(blob, width, text_columns)
        self.metrics["loaded_rows"] += len(found)
        self.memory[key] = found
        self.bytes += found.size
        while self.bytes > self.limit and len(self.memory) > 1:
            _, old = self.memory.popitem(last=False)
            self.bytes -= old.size
        return found

    def close(self):
        self.memory.clear()
        if self.db is not None:
            try:
                size = self.db.execute(
                    "SELECT coalesce(sum(length(blob)),0) FROM buckets"
                ).fetchone()[0]
                if size > self.disk_limit:
                    with self.db:
                        for key, length in self.db.execute(
                            "SELECT key,length(blob) FROM buckets ORDER BY rowid"
                        ).fetchall():
                            self.db.execute("DELETE FROM buckets WHERE key=?", (key,))
                            size -= length
                            if size <= self.disk_limit:
                                break
                    self.db.execute("VACUUM")
            finally:
                self.db.close()


class Relations(Mapping):
    def __init__(self, index):
        self.index = index

    def __iter__(self):
        return iter(self.index.base.by_relation)

    def __len__(self):
        return len(self.index.base.by_relation)

    def __getitem__(self, relation):
        if relation not in self.index.base.by_relation:
            raise KeyError(relation)
        # Do not load buckets just to enumerate their keys or ask cardinalities.
        return self.index.base.by_relation[relation]


class CatalogIndex(FactIndex):
    """FactIndex protocol with vector exploration and semantic verification."""

    def __init__(self, base, *, cache_path=None, revision="", cache_mb=256):
        self.base, self.ir = base, base.ir
        self.by_relation = Relations(self)
        self.cache = BucketCache(
            cache_path, revision, disk_bytes=int(cache_mb * 1_000_000)
        )
        self.check = lambda: None
        self._endpoints = OrderedDict()
        self._retained_facts = 0

    def __getattr__(self, name):
        return getattr(self.base, name)

    @contextmanager
    def execution(self, check):
        previous, self.check = self.check, check
        try:
            with self.base.execution(check):
                yield
        finally:
            self.check = previous

    def _fact_bucket(self, relation, key, source):
        def produce():
            for f in source():
                yield f.subject, f.object, f._attributes, f._evidence

        records = self.cache.get(key, 4, FACT_TEXT, produce, self.check)

        def fact(row):
            return StoredFact(
                self.base.values, row[0], relation, row[1], row[2], row[3]
            )

        return RecordRows(records, fact)

    def rows(self, relation, subject=None, object=None):
        key = relation, subject, object
        found = self._endpoints.get(key)
        if found is not None:
            self._endpoints.move_to_end(key)
            return found
        result = self._rows(relation, subject, object)
        # Only retain detached small results. Caching a vector slice would pin
        # its entire bucket and bypass the vector cache's eviction policy.
        if isinstance(result, tuple):
            self._endpoints[key] = result
            self._retained_facts += len(result)
            while len(self._endpoints) > 16384 or self._retained_facts > 32768:
                _, removed = self._endpoints.popitem(last=False)
                self._retained_facts -= len(removed)
        return result

    def attr_rows(self, relation, key, value):
        return self.base.attr_rows(relation, key, value)

    def _rows(self, relation, subject=None, object=None):
        root = self.base.by_relation.get(relation)
        if root is None:
            return ()
        if len(root) <= MAX_BUCKET_ROWS:
            rows = self._fact_bucket(
                relation, ("relation", relation), lambda: self.base.rows(relation)
            )
            constraints = {}
            if subject is not None:
                constraints[0] = subject
            if object is not None:
                constraints[1] = object
            result = RecordRows(
                rows.records, rows.factory, rows.records.select(constraints)
            )
            return tuple(result) if len(result) <= 32 else result
        # Large relations are partitioned by their known object (e.g. ENTITY
        # kind). Unbounded large scans remain streaming in the semantic index.
        if object is not None:
            source = self.base.rows(relation, object=object)
            if len(source) <= MAX_BUCKET_ROWS:
                rows = self._fact_bucket(
                    relation, ("object", relation, object), lambda: source
                )
                result = RecordRows(
                    rows.records,
                    rows.factory,
                    rows.records.select({0: subject} if subject is not None else {}),
                )
                return tuple(result) if len(result) <= 32 else result
        self.cache.metrics["fallback"] += 1
        return self.base.rows(relation, subject, object)

    def candidates(self, clause, subject=None, object=None):
        from ken.structural.query import _variable

        if not clause.attrs:
            from ken.structural.query import QuotedTerm, _variable

            def endpoint(term, bound):
                if bound is not None or _variable(term) or term == "_":
                    return bound
                if isinstance(term, QuotedTerm):
                    return term.literal
                choices = tuple(term.split("|"))
                return choices[0] if len(choices) == 1 else choices

            selected_subject = endpoint(clause.subject, subject)
            selected_object = endpoint(clause.object, object)
            if any(isinstance(v, tuple) for v in (selected_subject, selected_object)):
                root = self.base.by_relation.get(clause.relation, ())
                if len(root) > MAX_BUCKET_ROWS:
                    source = self.base.candidates(clause, subject, object)
                    # A large ENTITY relation can still have a small union of
                    # type kinds. Share that selective seed across role names
                    # and catalogue roots instead of repeating its SQL scan.
                    if subject is None and len(source) <= MAX_BUCKET_ROWS:
                        return self._fact_bucket(
                            clause.relation,
                            (
                                "alternatives",
                                clause.relation,
                                selected_subject,
                                selected_object,
                            ),
                            lambda: source,
                        )
                    self.cache.metrics["fallback"] += 1
                    return source
            subject, object = selected_subject, selected_object
            return self.rows(clause.relation, subject, object)
        source = self.base.candidates(clause, subject, object)
        if subject is None and len(source) <= MAX_BUCKET_ROWS:
            return self._fact_bucket(
                clause.relation,
                (
                    "clause",
                    ("role",) if _variable(clause.subject) else clause.subject,
                    clause.relation,
                    ("role",) if _variable(clause.object) else clause.object,
                    tuple(clause.attrs),
                    subject,
                    object,
                ),
                lambda: source,
            )
        return source

    def operations(
        self, *, owner=None, kind=None, local_id=None, ordinal=None, region=None
    ):
        if owner is None or ordinal is not None or region is not None:
            yield from self.base.operations(
                owner=owner,
                kind=kind,
                local_id=local_id,
                ordinal=ordinal,
                region=region,
            )
            return

        def produce():
            for op in self.base.operations(owner=owner):
                yield (
                    op.id,
                    op.kind,
                    op.native_kind,
                    op.parent,
                    op.role,
                    op.start,
                    op.end,
                    op.line,
                    op.owner,
                    op._attributes,
                )

        records = self.cache.get(
            ("operations", owner), 10, OP_TEXT, produce, self.check
        )
        constraints = {}
        if kind is not None:
            constraints[1] = kind
        if local_id is not None:
            constraints[0] = local_id
        for position in records.select(constraints):
            yield StoredOperation(self.base.values, *records.row(position))

    def source_view(self):
        from ken.structural_store.graph_source import GraphSourceView

        return GraphSourceView(self)

    def close(self):
        self._endpoints.clear()
        self._retained_facts = 0
        self.cache.close()
