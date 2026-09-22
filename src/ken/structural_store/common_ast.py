"""Canonical AST persistence, indexed views and safe lazy projection of old units."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import fields
from typing import TYPE_CHECKING, Any

from ken.common_ast import (
    VERSION,
    Link,
    Node,
    Program,
    Reference,
    Scope,
    Symbol,
    normalize,
)
from ken.common_ast.boundaries import BodyRange, body_ranges

from .ast_columns import IDENTITIES, LAYOUTS, columns

if TYPE_CHECKING:
    from .store import Store

CLASSES = {"nodes": Node, "scopes": Scope, "symbols": Symbol, "references": Reference}


def project(store: Store, unit: int, program: Program) -> None:
    program.validate()
    store.db.execute("INSERT INTO k2_ast_units VALUES (?,?)", (unit, VERSION))
    strings: dict[str, int] = {}

    def intern(value: str) -> int:
        if value not in strings:
            strings[value] = len(strings)
        return strings[value]

    for family, (_, string_names, tuple_names) in LAYOUTS.items():
        names = columns(family)
        sql = f"INSERT INTO k2_ast_{family} VALUES ({','.join('?' for _ in range(len(names) + 1))})"
        for record in getattr(program, family):
            identity = getattr(record, "id", getattr(record, "node", None))
            values = [unit]
            for field in fields(record):
                value = getattr(record, field.name)
                if field.name in tuple_names.split():
                    store.db.executemany(
                        "INSERT INTO k2_ast_members VALUES (?,?,?,?,?,?)",
                        (
                            (unit, family, identity, field.name, i, intern(item))
                            for i, item in enumerate(value)
                        ),
                    )
                else:
                    values.append(
                        intern(value) if field.name in string_names.split() else value
                    )
            store.db.execute(sql, values)
    store.db.executemany(
        "INSERT INTO k2_ast_links VALUES (?,?,?,?,?)",
        ((unit, l.source, l.relation, l.target, l.ordinal) for l in program.links),
    )
    store.db.executemany(
        "INSERT INTO k2_ast_strings VALUES (?,?,?)",
        ((unit, i, value) for value, i in strings.items()),
    )
    store.db.executemany(
        "INSERT INTO k2_ast_diagnostics VALUES (?,?,?)",
        ((unit, i, message) for i, message in enumerate(program.diagnostics)),
    )
    store.db.executemany(
        "INSERT INTO k2_ast_bodies VALUES (?,?,?,?,?,?)",
        (
            (unit, r.owner, r.relation, r.root, r.subtree_end, r.final_node)
            for r in body_ranges(program)
        ),
    )


def ensure(store: Store, unit: int) -> Program | None:
    row = store.db.execute(
        "SELECT version FROM k2_ast_units WHERE unit_id=?", (unit,)
    ).fetchone()
    if row is not None and row[0] == VERSION:
        return None
    program = normalize(store.load_unit(unit))
    try:
        with store.transaction():
            store.db.execute("DELETE FROM k2_ast_units WHERE unit_id=?", (unit,))
            project(store, unit, program)
    except MemoryError:
        return program
    return None


class View:
    def __init__(self, store: Store, unit: int):
        self.store, self.unit = store, unit
        self.fallback = ensure(store, unit)
        self.strings = (
            dict(
                store.db.execute(
                    "SELECT string_id,value FROM k2_ast_strings WHERE unit_id=?",
                    (unit,),
                )
            )
            if self.fallback is None
            else {}
        )
        self._rows: dict[str, tuple] = {}
        self.members: dict[tuple, list[str]] = {}
        if self.fallback is None:
            for family, identity, field, value in store.db.execute(
                "SELECT family,record_id,field,value FROM k2_ast_members WHERE unit_id=? ORDER BY family,record_id,field,ordinal",
                (unit,),
            ):
                self.members.setdefault((family, identity, field), []).append(
                    self.strings[value]
                )

    def decode(self, kind: str, data):
        cls = CLASSES[kind]
        _, string_names, tuple_names = LAYOUTS[kind]
        row = dict(zip(columns(kind), data))
        identity = row[IDENTITIES[kind]]
        from .ast_columns import column

        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name in tuple_names.split():
                values[field.name] = tuple(
                    self.members.get((kind, identity, field.name), ())
                )
            else:
                value = row[column(kind, field.name)]
                values[field.name] = (
                    self.strings[value] if field.name in string_names.split() else value
                )
        if kind == "symbols" and values["mutable"] is not None:
            values["mutable"] = bool(values["mutable"])
        return cls(**values)

    @staticmethod
    def selection(kind):
        return ",".join('"' + name + '"' for name in columns(kind))

    def bodies(self, owner: int, relation: str = "body") -> tuple[BodyRange, ...]:
        if self.fallback is not None:
            return tuple(
                r
                for r in body_ranges(self.fallback)
                if r.owner == owner and r.relation == relation
            )
        return tuple(
            BodyRange(*row)
            for row in self.store.db.execute(
                "SELECT owner,relation,root,subtree_end FROM k2_ast_bodies WHERE unit_id=? AND owner=? AND relation=? ORDER BY root",
                (self.unit, owner, relation),
            )
        )

    def body_nodes(self, owner: int, relation: str = "body") -> Iterator[Node]:
        for body in self.bodies(owner, relation):
            if self.fallback is not None:
                yield from self.fallback.nodes[body.root : body.subtree_end]
            else:
                for row in self.store.db.execute(
                    "SELECT "
                    + self.selection("nodes")
                    + " FROM k2_ast_nodes WHERE unit_id=? AND node_id>=? AND node_id<? ORDER BY node_id",
                    (self.unit, body.root, body.subtree_end),
                ):
                    yield self.decode("nodes", row)

    def nodes(
        self,
        *,
        kind: str | None = None,
        name: str | None = None,
        parent: int | None = None,
        descendant_of: Node | None = None,
        scope: int | None = None,
    ) -> Iterator[Node]:
        if self.fallback is not None:
            for node in self.fallback.nodes:
                if (
                    (kind is None or node.kind == kind)
                    and (name is None or node.name == name)
                    and (parent is None or node.parent == parent)
                    and (scope is None or node.scope == scope)
                    and (
                        descendant_of is None
                        or descendant_of.id < node.id < descendant_of.subtree_end
                    )
                ):
                    yield node
            return
        sql = "SELECT " + self.selection("nodes") + " FROM k2_ast_nodes WHERE unit_id=?"
        args: list = [self.unit]
        for column, value in (("kind", kind), ("name", name)):
            if value is not None:
                sql += f" AND {column}=(SELECT string_id FROM k2_ast_strings WHERE unit_id=? AND value=?)"
                args.extend((self.unit, value))
        if parent is not None:
            sql += " AND parent=?"
            args.append(parent)
        if scope is not None:
            sql += " AND scope=?"
            args.append(scope)
        if descendant_of is not None:
            sql += " AND node_id>? AND node_id<?"
            args.extend((descendant_of.id, descendant_of.subtree_end))
        sql += " ORDER BY node_id"
        for data in self.store.db.execute(sql, args):
            yield self.decode("nodes", data)

    def rows(self, kind: str):
        if kind not in ("scopes", "symbols", "references"):
            raise ValueError("unsupported AST row family")
        if self.fallback is not None:
            return getattr(self.fallback, kind)
        if kind in self._rows:
            return self._rows[kind]
        identity = {
            "scopes": "scope_id",
            "symbols": "symbol_id",
            "references": "node_id",
        }[kind]
        result = tuple(
            self.decode(kind, data)
            for data in self.store.db.execute(
                f"SELECT {self.selection(kind)} FROM k2_ast_{kind} WHERE unit_id=? ORDER BY {identity}",
                (self.unit,),
            )
        )
        self._rows[kind] = result
        return result

    def declarations(self, scope: int, name: str, point: int) -> tuple[Symbol, ...]:
        if self.fallback is not None:
            return tuple(
                sorted(
                    (
                        s
                        for s in self.fallback.symbols
                        if s.scope == scope
                        and s.name == name
                        and s.visible_from <= point
                    ),
                    key=lambda s: s.visible_from,
                    reverse=True,
                )
            )
        return tuple(
            self.decode("symbols", data)
            for data in self.store.db.execute(
                f"""
            SELECT {self.selection("symbols")} FROM k2_ast_symbols WHERE unit_id=? AND scope=? AND name=(
              SELECT string_id FROM k2_ast_strings WHERE unit_id=? AND value=?)
            AND visible_from<=? ORDER BY visible_from DESC""",
                (self.unit, scope, self.unit, name, point),
            )
        )

    def references_to(self, symbol: int) -> tuple[Reference, ...]:
        if self.fallback is not None:
            return tuple(r for r in self.fallback.references if r.symbol == symbol)
        return tuple(
            self.decode("references", data)
            for data in self.store.db.execute(
                "SELECT "
                + self.selection("references")
                + " FROM k2_ast_references WHERE unit_id=? AND symbol=? ORDER BY node_id",
                (self.unit, symbol),
            )
        )


def load(store: Store, unit: int) -> Program:
    view = View(store, unit)
    if view.fallback is not None:
        return view.fallback
    path, language = store.db.execute(
        "SELECT path,language FROM k2_units WHERE unit_id=?", (unit,)
    ).fetchone()
    diagnostics = tuple(
        message
        for (message,) in store.db.execute(
            "SELECT message FROM k2_ast_diagnostics WHERE unit_id=? ORDER BY ordinal",
            (unit,),
        )
    )
    links = tuple(
        Link(*row)
        for row in store.db.execute(
            "SELECT source,relation,target,ordinal FROM k2_ast_links WHERE unit_id=? ORDER BY source,relation,ordinal,target",
            (unit,),
        )
    )
    program = Program(
        path,
        language,
        tuple(view.nodes()),
        view.rows("scopes"),
        view.rows("symbols"),
        view.rows("references"),
        links,
        tuple(diagnostics),
    )
    program.validate()
    return program
