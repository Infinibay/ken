"""Validate plan dependencies and role domains without retaining an executor."""

from __future__ import annotations

from collections.abc import Set
from typing import TYPE_CHECKING

from .query import QuotedTerm

if TYPE_CHECKING:
    from .relational_ir import Node, Query


def validate(root: Query, queries: dict[str, Query], relations: Set[str]) -> None:
    visited: dict[str, dict[str, set[str]]] = {}

    def infer(q: Query, stack: list[str]) -> dict[str, set[str]]:
        kinds: dict[str, set[str]] = {}

        def constrain(role: str, allowed: set[str]) -> None:
            if not role.startswith("$") or not allowed:
                return
            if role in kinds:
                allowed = kinds[role] & allowed
                if not allowed:
                    raise ValueError(f"incompatible role kinds for {role} in {q.name}")
            kinds[role] = allowed

        def walk(nodes: list[Node]) -> None:
            for node in nodes:
                if node.kind == "fact":
                    c = node.value
                    if c.relation not in relations:
                        raise ValueError(f"unknown graph relation {c.relation}")
                    if (
                        c.relation in {"ENTITY", "IS"}
                        and not c.object.startswith("$")
                        and c.object != "_"
                    ):
                        constrain(
                            c.subject,
                            {c.object.literal}
                            if isinstance(c.object, QuotedTerm)
                            else set(c.object.split("|")),
                        )
                elif node.kind == "path":
                    if node.value[1] not in relations:
                        raise ValueError(f"unknown graph relation {node.value[1]}")
                elif node.kind == "match":
                    name, bindings, _ = node.value
                    if name not in queries:
                        raise ValueError(f"unknown named query {name}")
                    if name in stack:
                        raise ValueError(
                            "query dependency cycle: " + " -> ".join(stack + [name])
                        )
                    child = queries[name]
                    if not set(bindings) <= child.exports.keys():
                        raise ValueError(
                            f"{name}: unknown export roles {sorted(set(bindings) - child.exports.keys())}"
                        )
                    if name not in visited:
                        visited[name] = infer(child, stack + [name])
                    for public, local in bindings.items():
                        constrain(local, visited[name].get(public, set()))
                elif node.kind == "any":
                    # Alternative shapes may expose a union (class OR generator).
                    outer = dict(kinds)
                    alternatives = []
                    for branch in node.children:
                        kinds.clear()
                        kinds.update(outer)
                        walk(branch)
                        alternatives.append(dict(kinds))
                    kinds.clear()
                    kinds.update(outer)
                    for role in set.intersection(*(set(a) for a in alternatives)):
                        kinds[role] = set.union(*(a[role] for a in alternatives))
                else:
                    for branch in node.children:
                        outer = dict(kinds)
                        walk(branch)
                        kinds.clear()
                        kinds.update(outer)

        try:
            walk(q.nodes)
            return {name: kinds.get(role, set()) for name, role in q.exports.items()}
        finally:
            # Recursive local functions otherwise retain their closure after
            # validation, including every compiled dependency they traversed.
            del walk

    try:
        infer(root, [])
    finally:
        del infer
