"""Bounded dictionaries for graph identities and repeated metadata strings."""

from collections import OrderedDict
from functools import lru_cache


class Terms:
    def __init__(self, db, graph):
        self.db, self.graph = db, graph
        self.next_id = db.execute(
            "SELECT coalesce(max(term_id),0) FROM k2_graph_terms WHERE graph_id=?",
            (graph,),
        ).fetchone()[0]
        self.cache: OrderedDict[str, int] = OrderedDict()

    def put(self, value: str | None) -> int | None:
        if value is None:
            return None
        found = self.cache.get(value)
        if found is not None:
            self.cache.move_to_end(value)
            return found
        row = self.db.execute(
            "SELECT term_id FROM k2_graph_terms WHERE graph_id=? AND text=?",
            (self.graph, value),
        ).fetchone()
        if row is None:
            self.next_id += 1
            found = self.next_id
            self.db.execute(
                "INSERT INTO k2_graph_terms VALUES (?,?,?)", (self.graph, found, value)
            )
        else:
            found = row[0]
        self.cache[value] = found
        if len(self.cache) > 65536:
            self.cache.popitem(last=False)
        return found


class TermReader:
    def __init__(self, db, graph):
        self.db, self.graph = db, graph
        self.get = lru_cache(maxsize=4096)(self._get)

    def _get(self, code):
        if code is None:
            return None
        row = self.db.execute(
            "SELECT text FROM k2_graph_terms WHERE graph_id=? AND term_id=?",
            (self.graph, code),
        ).fetchone()
        if row is None:
            raise ValueError("missing graph dictionary entry")
        return row[0]
