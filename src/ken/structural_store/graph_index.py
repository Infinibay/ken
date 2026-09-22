"""Lazy relational access to a normalized graph; no project deserialization.

The executor consumes the same FactIndex protocol as its in-memory reference.
SQLite handles indexed candidate selection and counts; Python handles language
semantics, evidence and CFG matching on the selected candidates.
"""

from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from typing import Any

from ken.structural.model import IR_VERSION, FactIndex

from .graph_control import ReadConnection
from .graph_records import GraphView, StoredEntity, StoredFact, StoredOperation
from .graph_rows import Capabilities, Entities, FactRows, Operations, fact_table
from .graph_values import ValueReader
from .leases import renew


class GraphIndex(FactIndex):
    """Read-only index. Its owning Store must outlive all query iterators."""

    def __init__(self, store, graph: int, *, owns_store=False):
        self.store, self.db, self.graph = store, ReadConnection(store.db), graph
        self.owns_store = owns_store
        self.values = ValueReader(self.db, graph)
        self.words = self.values.words.get
        self.term = lru_cache(maxsize=65536)(self._term)
        self._cached_endpoint_rows = lru_cache(maxsize=16384)(self._rows)
        self.count_rows = lru_cache(maxsize=8192)(self._count_rows)
        self._small_rows = lru_cache(maxsize=8192)(self._probe_small_rows)
        self._row_cache: OrderedDict[tuple, tuple[StoredFact, ...]] = OrderedDict()
        self._cached_records = 0
        self._coverage: dict[bool, tuple[set[str], set[str], set[str]]] = {}
        self._missing_calls = None
        self._operation_owners: dict[frozenset[str], frozenset[str]] = {}
        row = self.db.execute(
            "SELECT path,language,version,view,metadata FROM k2_graphs JOIN k2_graph_publications USING(graph_id) WHERE graph_id=? AND ready=1",
            (graph,),
        ).fetchone()
        if row is None:
            raise KeyError(graph)
        path, language, version, view, metadata = row
        if version != IR_VERSION or view != "query":
            raise ValueError("incompatible query graph index")
        from .graph_syntax import ensure

        ensure(store, graph)
        meta = self.values.get(metadata)
        self.analysis = meta["analysis"]
        # The inherited facade predates disk-backed sequences. Its consumers
        # use ordered read-only buckets, never list-specific mutation methods.
        self.by_relation: Any = {
            name: FactRows(self, " AND f.relation=?", (relation,), count)
            for relation, name, count in self.db.execute(
                """
                SELECT r.relation,t.text,r.count FROM k2_graph_relations r
                JOIN k2_graph_terms t ON t.graph_id=r.graph_id AND t.term_id=r.relation
                WHERE r.graph_id=?""",
                (graph,),
            )
        }
        self.ir: Any = GraphView(
            path,
            language,
            version=version,
            view=view,
            entities=Entities(self, meta["entities"]),
            operations=Operations(self, meta["operations"]),
            facts=FactRows(self, count=meta["facts"]),
            capabilities=Capabilities(self),
            diagnostics=meta["diagnostics"],
            relations=set(meta["relations"]),
        )

    def _term(self, text):
        if not isinstance(text, str):
            return None
        row = self.db.execute(
            "SELECT term_id FROM k2_graph_terms WHERE graph_id=? AND text=?",
            (self.graph, text),
        ).fetchone()
        return row[0] if row else None

    def _count_rows(self, where, params, access):
        cached = self.cached_rows(where, params)
        if cached is not None:
            return len(cached)
        return self.db.execute(
            "SELECT count(*) FROM "
            + fact_table(where, access)
            + " WHERE f.graph_id=?"
            + where,
            (self.graph, *params),
        ).fetchone()[0]

    def cached_rows(self, where, params):
        key = where, params
        found = self._row_cache.get(key)
        if found is not None:
            self._row_cache.move_to_end(key)
        return found

    def _probe_small_rows(self, where, params, access):
        # At most 33 endpoint-index entries, without counting a large bucket.
        # This picks a physical strategy; no candidate is removed by the probe.
        return (
            self.db.execute(
                "SELECT 1 FROM "
                + fact_table(where, access)
                + " WHERE f.graph_id=?"
                + where
                + " LIMIT 1 OFFSET 32",
                (self.graph, *params),
            ).fetchone()
            is None
        )

    def retain_rows(self, where, params, rows):
        key = where, params
        old = self._row_cache.pop(key, ())
        self._cached_records += len(rows) - len(old)
        self._row_cache[key] = rows
        while len(self._row_cache) > 16384 or self._cached_records > 32768:
            _, removed = self._row_cache.popitem(last=False)
            self._cached_records -= len(removed)

    def rows(self, relation, subject=None, object=None):
        return self._cached_endpoint_rows(relation, subject, object)

    def _rows(self, relation, subject, object):
        base = self.by_relation.get(relation)
        if base is None:
            return ()
        if subject is None and object is None:
            return base
        where, params = base.where, list(base.params)
        for column, value in (("subject", subject), ("object", object)):
            if value is not None:
                term = self.term(value)
                if term is None:
                    return ()
                where += f" AND f.{column}=?"
                params.append(term)
        return FactRows(
            self, where, params, access="forward" if subject is not None else "reverse"
        )

    def attr_rows(self, relation, key, value):
        from .graph_operation_attributes import candidates

        base = self.by_relation.get(relation)
        if base is None:
            return ()
        sql, params = candidates(self, key, [value], operations=relation == "OPERATION")
        return FactRows(
            self,
            base.where + " AND f.attributes IN (" + sql + ")",
            (*base.params, *params),
            access="attribute",
        )

    def candidates(self, clause, subject=None, object=None):
        from ken.structural.query import QuotedTerm, _variable

        from .graph_operation_attributes import candidates

        base = self.rows(clause.relation, subject, object)
        if not isinstance(base, FactRows):
            return base
        where, params, access = base.where, list(base.params), base.access
        correlated = subject is not None
        if not correlated and object is not None and clause.attrs:
            correlated = self._small_rows(base.where, base.params, base.access)
        for column, term, resolved in (
            ("subject", clause.subject, subject),
            ("object", clause.object, object),
        ):
            if (
                resolved is None
                and not isinstance(term, QuotedTerm)
                and not _variable(term)
                and "|" in term
            ):
                alternatives = [self.term(value) for value in term.split("|")]
                alternatives = [value for value in alternatives if value is not None]
                if not alternatives:
                    return ()
                where += f" AND f.{column} IN ({','.join('?' for _ in alternatives)})"
                params.extend(alternatives)
                if column == "subject":
                    access = "forward"
                elif access != "forward":
                    access = "reverse"
        for key, op, value in clause.attrs:
            if op not in ("=", "literal") or not value:
                continue
            alternatives = [value] if op == "literal" else value.split("|")
            sql, extra = candidates(
                self,
                key,
                alternatives,
                operations=clause.relation == "OPERATION",
                correlated=correlated,
            )
            if correlated:
                access = base.access
            elif access != "forward":
                access = "attribute"
            where += (
                (" AND EXISTS (" if correlated else " AND f.attributes IN (")
                + sql
                + ")"
            )
            params.extend(extra)
        return FactRows(self, where, params, access=access)

    def estimate_clause(self, clause, subject=None, object=None):
        # Count indexed necessary predicates. Regex/range/semantic filters remain
        # in the executor; planning must not materialize every row to count them.
        return len(self.candidates(clause, subject, object))

    def entities(self, *, kind=None, owner=None, source_owner=None, local_id=None):
        sql = """SELECT t.text,e.kind,e.name,e.path,e.line,e.end_line,e.attributes
            FROM k2_graph_entities e JOIN k2_graph_terms t
            ON t.graph_id=e.graph_id AND t.term_id=e.local_id WHERE e.graph_id=?"""
        params = [self.graph]
        for column, value, is_term in (
            ("kind", kind, True),
            ("owner", owner, True),
            ("source_owner", source_owner, True),
            ("local_id", local_id, True),
        ):
            if value is not None:
                resolved = self.term(value) if is_term else value
                if resolved is None:
                    return
                sql += f" AND e.{column}=?"
                params.append(resolved)
        for row in self.db.execute(sql + " ORDER BY e.ordinal", params):
            identity, kind_code, name, path_code, line, end_line, attrs = row
            yield StoredEntity(
                self.values,
                identity,
                self.words(kind_code),
                name,
                self.words(path_code),
                line,
                end_line,
                attrs,
            )

    def operations(
        self, *, owner=None, kind=None, local_id=None, ordinal=None, region=None
    ):
        table = "k2_graph_operations o"
        if ordinal is None:
            # ORDER BY ordinal can otherwise make SQLite prefer a project-wide
            # primary-key scan, even for one local ID. Bind the physical access
            # to the known endpoint, as fact posting lists already do.
            for access, value in (("id", local_id), ("owner", owner),
                                  ("kind", kind), ("id", region)):
                if value is not None:
                    table += f" INDEXED BY k2_graph_operation_{access}"
                    break
        sql = """SELECT t.text,o.kind,o.native_kind,p.text,o.role,o.start_byte,o.end_byte,o.line,w.text,o.attributes
            FROM """ + table + """
            JOIN k2_graph_terms t ON t.graph_id=o.graph_id AND t.term_id=o.local_id
            JOIN k2_graph_terms w ON w.graph_id=o.graph_id AND w.term_id=o.owner
            LEFT JOIN k2_graph_terms p ON p.graph_id=o.graph_id AND p.term_id=o.parent
            WHERE o.graph_id=?"""
        params = [self.graph]
        for column, value, is_term in (
            ("owner", owner, True),
            ("kind", kind, True),
            ("local_id", local_id, True),
            ("ordinal", ordinal, False),
        ):
            if value is not None:
                resolved = self.term(value) if is_term else value
                if resolved is None:
                    return
                sql += f" AND o.{column}=?"
                params.append(resolved)
        if region is not None:
            bounds = self.syntax_bounds(region.id)
            if bounds is None:
                return
            sql += " AND o.local_id IN (SELECT local_id FROM k2_graph_syntax WHERE graph_id=? AND position>=? AND position<?)"
            params.extend((self.graph, bounds[0], bounds[1]))
        for *fields, attrs in self.db.execute(sql + " ORDER BY o.ordinal", params):
            fields[1], fields[2], fields[4] = (self.words(fields[i]) for i in (1, 2, 4))
            yield StoredOperation(self.values, *fields, attrs)

    def operation_owners(self, kinds: frozenset[str]) -> frozenset[str]:
        """Owners with a syntax operation of these kinds, without decoding it."""
        cached = self._operation_owners.get(kinds)
        if cached is not None:
            return cached
        terms = tuple(term for kind in sorted(kinds)
                      if (term := self.term(kind)) is not None)
        owners = frozenset(
            row[0] for row in self.db.execute(
                """SELECT DISTINCT t.text
                FROM k2_graph_operations o INDEXED BY k2_graph_operation_kind
                JOIN k2_graph_terms t ON t.graph_id=o.graph_id AND t.term_id=o.owner
                WHERE o.graph_id=? AND o.kind IN ("""
                + ",".join("?" for _ in terms) + ")", (self.graph, *terms)
            )
        ) if terms else frozenset()
        self._operation_owners[kinds] = owners
        return owners

    def syntax_bounds(self, local_id):
        """Return (inclusive preorder start, exclusive end, final syntax node ID)."""
        term = self.term(local_id)
        if term is None:
            return None
        return self.db.execute(
            """SELECT s.position,s.subtree_end,t.text FROM k2_graph_syntax s
            JOIN k2_graph_terms t ON t.graph_id=s.graph_id AND t.term_id=s.final_node
            WHERE s.graph_id=? AND s.local_id=?""",
            (self.graph, term),
        ).fetchone()

    def source_view(self):
        from .graph_source import GraphSourceView

        return GraphSourceView(self)

    def execution(self, check):
        def checkpoint():
            check()
            renew(self.store)

        return self.db.execution(checkpoint)

    def heartbeat(self):
        renew(self.store)

    def source_coverage(self, general=False):
        from .graph_coverage import coverage

        return coverage(self, general)

    def call_witnesses(self, names):
        call_kind = self.term("CALL")
        if not names or call_kind is None:
            return set(), set()
        witnesses = {
            row[0]
            for row in self.db.execute(
                """SELECT DISTINCT t.text
            FROM k2_graph_entities e JOIN k2_graph_terms t
            ON t.graph_id=e.graph_id AND t.term_id=e.owner
            WHERE e.graph_id=? AND e.kind=? AND e.name IN ("""
                + ",".join("?" for _ in names)
                + ")",
                (self.graph, call_kind, *names),
            )
        }
        if self._missing_calls is not None:
            return witnesses, self._missing_calls
        # Missing semantic call occurrences can produce unknown BODY matches.
        # This anti-join compares indexed integer owners and byte ranges.
        missing = {
            row[0]
            for row in self.db.execute(
                """SELECT DISTINCT t.text
            FROM k2_graph_operations o JOIN k2_graph_terms t
            ON t.graph_id=o.graph_id AND t.term_id=o.owner
            WHERE o.graph_id=? AND o.kind=? AND NOT EXISTS (
                SELECT 1 FROM k2_graph_entities e WHERE e.graph_id=o.graph_id
                AND e.kind=? AND e.owner=o.owner
                AND e.start_byte IS o.start_byte AND e.end_byte IS o.end_byte)""",
                (self.graph, call_kind, call_kind),
            )
        }
        # An empty primary spelling may have a name only in ENTITY facts. Keep
        # those owners as candidates instead of deriving an unjustified denial.
        missing.update(
            row[0]
            for row in self.db.execute(
                """SELECT DISTINCT t.text
            FROM k2_graph_entities e JOIN k2_graph_terms t
            ON t.graph_id=e.graph_id AND t.term_id=e.owner
            WHERE e.graph_id=? AND e.kind=? AND e.name='' """,
                (self.graph, call_kind),
            )
        )
        self._missing_calls = missing
        return witnesses, missing

    def close(self):
        self.term.cache_clear()
        self._cached_endpoint_rows.cache_clear()
        self.count_rows.cache_clear()
        self._small_rows.cache_clear()
        self._row_cache.clear()
        self._coverage.clear()
        self._operation_owners.clear()
        self._missing_calls = None
        self.ir.entities.get_entity.cache_clear()
        self.values.cache.clear()
        self.values.words.get.cache_clear()
        if self.owns_store:
            self.owns_store = False
            self.store.close()
