"""Immutable semantic facts retained by a prepared reader, including disk spill."""
from __future__ import annotations

from collections.abc import Callable
import json
import sqlite3

from ken.structural.model import IR


def exceeds_allowance(graph: IR, allowance: int, check: Callable[[], None]) -> bool:
    """Prefer spill when estimated fact storage exceeds cache headroom.

    The estimate includes row/index cells, dictionary text and JSON payloads.
    It can prefer private storage for a graph that might fit in page slack.
    Commit still checks actual allocation for admitted graphs. No facts or
    query answers are dropped.
    """
    terms: set[str] = set()
    # A fact has a table cell, its ordinal key and two directional lookup cells.
    # Estimate their small integer keys/record headers before text payloads.
    size = 64 * len(graph.facts)
    if size > allowance:
        return True
    for ordinal, fact in enumerate(graph.facts):
        if ordinal % 1000 == 0:
            check()
        for word in (fact.subject, fact.relation, fact.object):
            if word not in terms:
                terms.add(word)
                # The dictionary stores text in its table and unique index.
                size += 2 * len(word)
        size += len(json.dumps(fact.attrs)) + len(json.dumps(fact.evidence))
        if size > allowance:
            return True
    return False


def write_facts(db: sqlite3.Connection, snapshot: int, graph: IR, check: Callable[[], None],
                *, bulk: bool = False) -> None:
    """Persist every fact with one shared copy of each identity per snapshot."""
    # The caller owns a write transaction. Rebuild secondary indexes in bulk
    # instead of churning their leaf pages on every insertion. Existing readers
    # retain their previous schema until publication; rollback restores it too.
    # Lazy evaluation may have a live scan on this connection, which prevents
    # DDL. Only explicit preparation owns the connection without active scans.
    indexes = (db.execute("SELECT name,sql FROM sqlite_master WHERE type='index' "
                          "AND name IN ('k2_semantic_row_forward','k2_semantic_row_reverse')").fetchall()
               if bulk else [])
    for name, _ in indexes:
        db.execute('DROP INDEX ' + name)
    terms: dict[str, int] = {}
    for ordinal, fact in enumerate(graph.facts):
        if ordinal % 1000 == 0:
            check()
        for word in (fact.subject, fact.relation, fact.object):
            if word not in terms:
                terms[word] = len(terms) + 1
    # Both dictionary keys grow monotonically; long identifier prefixes then
    # occupy adjacent pages instead of forcing random unique-index writes.
    terms = {word: term for term, word in enumerate(sorted(terms), 1)}
    def term_rows():
        for ordinal, (word, term) in enumerate(terms.items()):
            if ordinal % 1000 == 0:
                check()
            yield snapshot, term, word
    db.executemany('INSERT INTO k2_semantic_terms VALUES (?,?,?)', term_rows())
    db.executemany('INSERT INTO k2_semantic_rows VALUES (?,?,?,?,?,?,?)',
                   fact_rows(snapshot, graph, terms, check))
    for _, sql in indexes:
        check()
        db.execute(sql)


def fact_rows(snapshot: int, graph: IR, terms: dict[str, int], check: Callable[[], None]):
    for ordinal, fact in enumerate(graph.facts):
        if ordinal % 1000 == 0:
            check()
        yield (snapshot, ordinal, terms[fact.subject], terms[fact.relation], terms[fact.object],
               json.dumps(fact.attrs), json.dumps(fact.evidence))


class SemanticIndex:
    """Own only immutable facts; bindings, budgets and answers stay per query."""

    def __init__(self, db: sqlite3.Connection, snapshot: int, *, owned: bool = False):
        self.db, self.snapshot, self.owned = db, snapshot, owned
        self.storage = 'session_disk' if owned else 'shared_disk'

    @classmethod
    def spill(cls, source: sqlite3.Connection, snapshot: int, graph: IR,
              check: Callable[[], None]) -> SemanticIndex:
        # SQLite's empty filename is a private on-disk database, removed on close.
        # Keep the shared cache quota intact without retaining a project-sized
        # Python fact dictionary or rebuilding it for every request.
        db = sqlite3.connect('')
        try:
            from ken.structural_store.semantic_dictionary import TABLE_STATEMENTS, INDEX_STATEMENTS, VIEW

            db.execute('PRAGMA cache_size=-65536')
            db.execute(source.execute("SELECT sql FROM sqlite_master WHERE name='k2_analysis'").fetchone()[0])
            for sql in TABLE_STATEMENTS:
                db.execute(sql)
            db.execute('INSERT INTO k2_analysis VALUES (?,?,?)',
                       (snapshot, json.dumps(sorted(graph.capabilities)), json.dumps(graph.diagnostics)))
            write_facts(db, snapshot, graph, check)
            for sql in INDEX_STATEMENTS + (VIEW,):
                check()
                db.execute(sql)
            db.commit()
            db.execute('PRAGMA query_only=ON')
            return cls(db, snapshot, owned=True)
        except BaseException:
            db.close()
            raise

    def close(self) -> None:
        if self.owned:
            self.db.close()
