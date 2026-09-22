"""Publish large graphs in bounded transactions without exposing partial data."""

import time
from contextlib import contextmanager
from itertools import islice

from .leases import TTL_NS, SnapshotExpired, renew

STATEMENTS = (
    """CREATE TABLE k2_graph_publications(graph_id INTEGER PRIMARY KEY REFERENCES k2_graphs ON DELETE CASCADE,
        ready INTEGER NOT NULL CHECK(ready IN (0,1)), lease_id TEXT)""",
    "INSERT INTO k2_graph_publications SELECT graph_id,1,NULL FROM k2_graphs",
)
TABLES = ("k2_graph_publications",)


class Publication:
    """Only the final READY transition makes a graph available to readers.

    Committing batches lets SQLite checkpoint its WAL during acquisition. Failed
    publications are removed; abandoned builds can be replaced once their writer
    lease has expired. Explicit resume requires the identical ordered input.
    Existing completed revisions remain readable throughout.
    """

    def __init__(
        self, store, snapshot, key, ir, check=None, progress=None, *, resume=False
    ):
        self.store, self.snapshot, self.key, self.ir = store, snapshot, key, ir
        self.check, self.progress = check, progress
        self.graph = None
        self.existing = False
        self.resumed = False
        self.allow_resume = resume

    @contextmanager
    def transaction(self):
        with self.store.transaction(retry_busy=self.waiting):
            self.checkpoint()
            yield

    def waiting(self):
        # An index migration may hold the writer lock longer than busy_timeout.
        # No rows have been consumed yet. Ownership is rechecked after acquiring
        # the lock, so a replacement publisher still cannot be overwritten.
        if self.check is not None:
            self.check()

    def checkpoint(self):
        # Recheck ownership under the writer lock even when the periodic lease
        # renewal is not due. Wall time can advance while a laptop is asleep.
        if self.graph is not None and self.store.lease_id is not None:
            owner = self.store.db.execute(
                "SELECT lease_id FROM k2_graph_publications WHERE graph_id=? AND ready=0",
                (self.graph,),
            ).fetchone()
            if owner != (self.store.lease_id,):
                raise SnapshotExpired("query graph publication ownership changed")
            self.store.db.execute(
                """INSERT INTO k2_leases VALUES (?,NULL,?)
                ON CONFLICT(lease_id) DO UPDATE SET expires_ns=excluded.expires_ns
                WHERE k2_leases.expires_ns<=?""",
                (self.store.lease_id, time.time_ns() + TTL_NS, time.time_ns()),
            )
        if self.check is not None:
            self.check()
        renew(self.store)

    def __enter__(self):
        with self.transaction():
            found = self.store.db.execute(
                """SELECT g.graph_id,p.ready,p.lease_id
                FROM k2_graphs g JOIN k2_graph_publications p USING(graph_id)
                WHERE g.fingerprint=?""",
                (self.key,),
            ).fetchone()
            if found:
                graph, ready, lease = found
                if ready:
                    self.graph, self.existing = graph, True
                    return self
                active = self.store.db.execute(
                    "SELECT 1 FROM k2_leases WHERE lease_id=? AND expires_ns>?",
                    (lease, time.time_ns()),
                ).fetchone()
                if active:
                    raise RuntimeError("query graph publication already in progress")
                if self.allow_resume:
                    self.graph, self.resumed = graph, True
                    self.store.db.execute(
                        "UPDATE k2_graph_publications SET lease_id=? WHERE graph_id=?",
                        (self.store.lease_id, graph),
                    )
                    return self
                self.store.db.execute(
                    "DELETE FROM k2_graphs WHERE graph_id=?", (graph,)
                )
            cursor = self.store.db.execute(
                """INSERT INTO k2_graphs
                (snapshot_id,fingerprint,path,language,version,view,metadata) VALUES (?,?,?,?,?,?,0)""",
                (
                    self.snapshot,
                    self.key,
                    self.ir.path,
                    self.ir.language,
                    self.ir.version,
                    self.ir.view,
                ),
            )
            self.graph = cursor.lastrowid
            self.store.db.execute(
                "INSERT INTO k2_graph_publications VALUES (?,0,?)",
                (self.graph, self.store.lease_id),
            )
        return self

    def position(self, table):
        if table not in {"k2_graph_entities", "k2_graph_operations", "k2_graph_facts"}:
            raise ValueError("not an ordered graph table")
        if not self.resumed:
            return 0
        return self.store.db.execute(
            f"SELECT coalesce(max(ordinal)+1,0) FROM {table} WHERE graph_id=?",
            (self.graph,),
        ).fetchone()[0]

    def insert(self, table, width, rows):
        count = (
            self.position(table)
            if table in {"k2_graph_entities", "k2_graph_operations", "k2_graph_facts"}
            else 0
        )
        iterator, exhausted = iter(rows), False
        sql = f"INSERT INTO {table} VALUES ({','.join('?' for _ in range(width))})"
        while not exhausted:
            with self.transaction():
                # Generation also writes dictionary values, so it belongs inside
                # the same bounded transaction as the rows that reference them.
                for _ in range(64):
                    batch = list(islice(iterator, 512))
                    if not batch:
                        exhausted = True
                        break
                    self.checkpoint()
                    self.store.db.executemany(sql, batch)
                    count += len(batch)
            if self.progress is not None and count and count % 262144 == 0:
                self.progress(table, count)
        if self.progress is not None:
            self.progress(table, count)

    def __exit__(self, kind, error, traceback):
        if self.existing:
            return
        if kind is None:
            try:
                with self.transaction():
                    self.store.db.execute(
                        "UPDATE k2_graph_publications SET ready=1,lease_id=NULL WHERE graph_id=?",
                        (self.graph,),
                    )
                return
            except BaseException:
                self.discard()
                raise
        self.discard()

    def discard(self):
        with self.store.transaction(reclamation=True):
            self.store.db.execute(
                """DELETE FROM k2_graphs WHERE graph_id=? AND EXISTS (
                    SELECT 1 FROM k2_graph_publications p WHERE p.graph_id=k2_graphs.graph_id
                    AND p.ready=0 AND p.lease_id IS ?)""",
                (self.graph, self.store.lease_id),
            )
