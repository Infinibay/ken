"""Ordered SQL posting lists and lazy entity/operation collections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from functools import lru_cache
from typing import Literal

from .graph_records import StoredFact


def fact_table(where, access):
    """Use the same physical access for enumeration, existence and estimates."""
    return "k2_graph_facts f" + (f" INDEXED BY k2_graph_fact_{access}" if where else "")


class FactRows(Sequence):
    def __init__(
        self,
        index,
        where="",
        params=(),
        count=None,
        access: Literal["relation", "forward", "reverse", "attribute"] = "relation",
    ):
        self._index, self.where, self.params = index, where, tuple(params)
        self._count = count
        self.access = access

    def __len__(self):
        if self._count is None:
            self._count = self._index.count_rows(self.where, self.params, self.access)
        return self._count

    def __bool__(self):
        if self._count is not None:
            return bool(self._count)
        cached = self._index.cached_rows(self.where, self.params)
        if cached is not None:
            return bool(cached)
        exists = (
            self._index.db.execute(
                "SELECT 1 FROM "
                + fact_table(self.where, self.access)
                + " WHERE f.graph_id=?"
                + self.where
                + " LIMIT 1",
                (self._index.graph, *self.params),
            ).fetchone()
            is not None
        )
        if not exists:
            self._count = 0
            self._index.retain_rows(self.where, self.params, ())
        return exists

    def sql(self):
        # ORDER BY ordinal must not persuade SQLite to scan the entire graph
        # primary key for a one-node lookup. Every alternative remains indexed
        # by graph+relation; prefer an exact subject, then attribute or object.
        table = fact_table(self.where, self.access)
        return (
            """SELECT s.text,r.text,o.text,f.attributes,f.evidence
            FROM """
            + table
            + """
            JOIN k2_graph_terms s ON s.graph_id=f.graph_id AND s.term_id=f.subject
            JOIN k2_graph_terms r ON r.graph_id=f.graph_id AND r.term_id=f.relation
            JOIN k2_graph_terms o ON o.graph_id=f.graph_id AND o.term_id=f.object
            WHERE f.graph_id=?"""
            + self.where
            + " ORDER BY f.ordinal",
            (self._index.graph, *self.params),
        )

    def __iter__(self):
        cached = self._index.cached_rows(self.where, self.params)
        if cached is not None:
            yield from cached
            return
        sql, params = self.sql()
        cursor = self._index.db.execute(sql, params)
        retained = []
        try:
            for row in cursor:
                fact = StoredFact(self._index.values, *row)
                if retained is not None:
                    if len(retained) < 32:
                        retained.append(fact)
                    else:
                        retained = None
                yield fact
        finally:
            cursor.close()
        if retained is not None:
            self._index.retain_rows(self.where, self.params, tuple(retained))

    def __getitem__(self, position):
        if isinstance(position, slice):
            start, stop, step = position.indices(len(self))
            if step != 1:
                return [self[i] for i in range(start, stop, step)]
            sql, params = self.sql()
            return [
                StoredFact(self._index.values, *row)
                for row in self._index.db.execute(
                    sql + " LIMIT ? OFFSET ?", (*params, max(0, stop - start), start)
                )
            ]
        if position < 0:
            position += len(self)
        if position < 0:
            raise IndexError(position)
        sql, params = self.sql()
        row = self._index.db.execute(
            sql + " LIMIT 1 OFFSET ?", (*params, position)
        ).fetchone()
        if row is None:
            raise IndexError(position)
        return StoredFact(self._index.values, *row)


class Entities(Mapping):
    def __init__(self, index, count):
        self.index, self.count = index, count
        self.get_entity = lru_cache(maxsize=1024)(self._get)

    def __len__(self):
        return self.count

    def __iter__(self):
        for row in self.index.db.execute(
            """SELECT t.text FROM k2_graph_entities e
            JOIN k2_graph_terms t ON t.graph_id=e.graph_id AND t.term_id=e.local_id
            WHERE e.graph_id=? ORDER BY e.ordinal""",
            (self.index.graph,),
        ):
            yield row[0]

    def __contains__(self, key):
        term = self.index.term(key)
        return (
            term is not None
            and self.index.db.execute(
                "SELECT 1 FROM k2_graph_entities WHERE graph_id=? AND local_id=?",
                (self.index.graph, term),
            ).fetchone()
            is not None
        )

    def _get(self, key):
        return next(self.index.entities(local_id=key), None)

    def __getitem__(self, key):
        found = self.get_entity(key)
        if found is None:
            raise KeyError(key)
        return found

    def values(self):
        return self.index.entities()

    def items(self):
        return ((entity.id, entity) for entity in self.values())


class Operations(Sequence):
    def __init__(self, index, count):
        self.index, self.count = index, count

    def __len__(self):
        return self.count

    def __iter__(self):
        return self.index.operations()

    def __getitem__(self, position):
        if isinstance(position, slice):
            return [self[i] for i in range(*position.indices(len(self)))]
        if position < 0:
            position += len(self)
        found = next(self.index.operations(ordinal=position), None)
        if found is None:
            raise IndexError(position)
        return found


class Capabilities(AbstractSet):
    def __init__(self, index):
        self.index = index

    def __len__(self):
        return self.index.db.execute(
            "SELECT count(*) FROM k2_graph_capabilities WHERE graph_id=?",
            (self.index.graph,),
        ).fetchone()[0]

    def __iter__(self):
        return (
            row[0]
            for row in self.index.db.execute(
                "SELECT capability FROM k2_graph_capabilities WHERE graph_id=?",
                (self.index.graph,),
            )
        )

    def __contains__(self, value):
        return (
            self.index.db.execute(
                "SELECT 1 FROM k2_graph_capabilities WHERE graph_id=? AND capability=?",
                (self.index.graph, value),
            ).fetchone()
            is not None
        )
