"""Lossless native SQLite values for extensible attributes and evidence.

Scalars occupy typed columns. Containers are ordered child rows, not serialized
documents. Deduplication shares storage, never mutable values handed to callers.
"""

from __future__ import annotations

import math
import sqlite3
from collections import OrderedDict
from hashlib import sha256
from typing import Any

from ken.structural.model import _attribute_key

from .graph_control import ReadConnection
from .graph_terms import TermReader, Terms


class ValueWriter:
    def __init__(self, db: sqlite3.Connection, graph: int, terms=None):
        self.db, self.graph = db, graph
        self.terms = terms if terms is not None else Terms(db, graph)
        self.next_id = db.execute(
            "SELECT coalesce(max(value_id),0) FROM k2_graph_values WHERE graph_id=?",
            (graph,),
        ).fetchone()[0]
        self.cache: OrderedDict[bytes, int] = OrderedDict()

    def put(self, value: Any) -> int:
        tag = type(value).__name__
        identity: Any
        children = []
        text = integer = real = None
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("graph attribute keys must be strings")
            children = [
                (key, self.put(item), _attribute_key(item))
                for key, item in value.items()
            ]
            identity = tuple((key, child) for key, child, _ in children)
        elif isinstance(value, (list, tuple, set)):
            items = sorted(value, key=repr) if isinstance(value, set) else value
            children = [(None, self.put(item), _attribute_key(item)) for item in items]
            identity = tuple(child for _, child, _ in children)
        elif value is None:
            identity = None
        elif type(value) is bool:
            identity = integer = int(value)
        elif type(value) is int:
            identity = value
            if -(2**63) <= value < 2**63:
                integer = value
            else:
                text = str(value)
        elif type(value) is float:
            identity = value.hex()
            if math.isfinite(value) and identity != "-0x0.0p+0":
                real = value
            else:
                text = identity
        elif type(value) is str:
            identity = text = value
        else:
            raise TypeError(f"unsupported graph attribute type: {tag}")
        signature = sha256(
            repr((tag, identity)).encode("utf-8", "surrogatepass")
        ).digest()
        cached = self.cache.get(signature)
        if cached is not None:
            self.cache.move_to_end(signature)
            return cached
        row = self.db.execute(
            "SELECT value_id FROM k2_graph_values WHERE graph_id=? AND signature=?",
            (self.graph, signature),
        ).fetchone()
        if row is None:
            self.next_id += 1
            found = self.next_id
            self.db.execute(
                "INSERT INTO k2_graph_values VALUES (?,?,?,?,?,?,?)",
                (
                    self.graph,
                    found,
                    signature,
                    self.terms.put(tag),
                    text,
                    integer,
                    real,
                ),
            )
            self.db.executemany(
                "INSERT INTO k2_graph_members VALUES (?,?,?,?,?,?)",
                (
                    (
                        self.graph,
                        found,
                        ordinal,
                        self.terms.put(key),
                        child,
                        self.terms.put(comparison),
                    )
                    for ordinal, (key, child, comparison) in enumerate(children)
                ),
            )
        else:
            found = row[0]
        self.cache[signature] = found
        if len(self.cache) > 16384:
            self.cache.popitem(last=False)
        return found


class ValueReader:
    def __init__(self, db: sqlite3.Connection | ReadConnection, graph: int):
        self.db, self.graph = db, graph
        self.words = TermReader(db, graph)
        # Cache immutable encodings, so separate query records cannot alias
        # mutable attribute dictionaries/lists. Limit both rows and text bytes.
        self.cache: OrderedDict[int, tuple] = OrderedDict()
        self.cache_bytes = 0

    def encoded(self, value: int) -> tuple:
        cached = self.cache.get(value)
        if cached is not None:
            self.cache.move_to_end(value)
            return cached
        if value < 0:
            from .graph_operation_attributes import encoded

            return encoded(self, value)
        row = self.db.execute(
            "SELECT tag,text_value,integer_value,real_value FROM k2_graph_values WHERE graph_id=? AND value_id=?",
            (self.graph, value),
        ).fetchone()
        if row is None:
            raise ValueError("missing graph attribute value")
        tag = self.words.get(row[0])
        row = (tag, *row[1:])
        if tag in ("dict", "list", "tuple", "set"):
            children = tuple(
                (self.words.get(key), child)
                for key, child in self.db.execute(
                    "SELECT key,child FROM k2_graph_members WHERE graph_id=? AND parent=? ORDER BY ordinal",
                    (self.graph, value),
                )
            )
            row = (tag, children)
        size = len(repr(row))
        if size <= 65536:
            self.cache[value] = row
            self.cache_bytes += size
            while len(self.cache) > 8192 or self.cache_bytes > 4_000_000:
                _, removed = self.cache.popitem(last=False)
                self.cache_bytes -= len(repr(removed))
        return row

    def member(self, value: int, key: str) -> Any:
        """Project one dictionary member; leave unrelated subtrees encoded."""
        row = self.encoded(value)
        if row[0] == "operation_attributes":
            from .graph_operation_attributes import member

            return member(self, row, key)
        if row[0] == "dict":
            return next((self.get(child) for name, child in row[1] if name == key), None)
        return self.get(value).get(key)

    def get(self, value: int) -> Any:
        row = self.encoded(value)
        tag = row[0]
        if tag == "operation_attributes":
            from .graph_operation_attributes import decode

            return decode(self, row)
        if tag == "dict":
            return {key: self.get(child) for key, child in row[1]}
        if tag in ("list", "tuple", "set"):
            values = (self.get(child) for _, child in row[1])
            return {"list": list, "tuple": tuple, "set": set}[tag](values)
        _, text, integer, real = row
        if tag == "NoneType":
            return None
        if tag == "str":
            return text
        if tag == "bool":
            return bool(integer)
        if tag == "int":
            return integer if integer is not None else int(text)
        if tag == "float":
            return real if real is not None else float.fromhex(text)
        raise ValueError(f"unknown graph attribute tag: {tag}")
