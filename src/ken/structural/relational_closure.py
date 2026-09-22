"""Compile the closure obligations of a plan independently of its witnesses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import relational_operators
from .relational_ir import Node

if TYPE_CHECKING:
    from .relational import Executor


def can_prove_closure(engine: Executor, nodes: list[Node]) -> bool:
    """Whether this plan can establish a closed inventory for any bindings.

    Source matchers report coverage per witness, never a closed inventory.
    That property belongs to the plan; a COUNT/NOT need not rediscover it for
    every outer row. A positive answer still needs the ordinary per-binding
    capability checks, including named-query seed and scope semantics.
    """
    key = id(nodes)
    cached = engine._closure_plans.get(key)
    if cached is not None and cached[0] is nodes:
        return cached[1]
    pending, seen = [nodes], set()
    plan = True
    while pending and plan:
        items = pending.pop()
        if id(items) in seen:
            continue
        seen.add(id(items))
        for node in items:
            spec = relational_operators.OPERATORS.get(node.kind)
            if spec is None or not spec.preserves_closure:
                plan = False
                break
            if node.kind == "match":
                pending.append(engine.queries[node.value[0]].nodes)
            pending.extend(node.children)
    engine._closure_plans[key] = nodes, plan
    return plan
