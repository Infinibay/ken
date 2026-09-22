"""Optional execution diagnostics, with no ownership of an executor or index."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .relational_ir import Node, Row, ScanConstraint

if TYPE_CHECKING:
    from .relational import Executor
    from .relational_operators import OperatorSpec


class ExecutionProfile:
    """Aggregate nested work by plan location, not by number of input rows."""

    def __init__(self) -> None:
        self.operators: list[dict[str, Any]] = []
        self.parent: int | None = None
        self.selection: dict[str, Any] = {}
        self.planning_ms = 0.0
        self._metrics: dict[tuple[int | None, int], dict[str, Any]] = {}

    @contextmanager
    def planning(self) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.planning_ms += (time.perf_counter() - started) * 1000

    def select(self, index: int, reason: str, estimates=()) -> None:
        self.selection = {
            "reason": reason,
            "estimated_rows_per_input": next(
                (size for position, size in estimates if position == index), None
            ),
            "alternatives": [
                {"position": position, "estimated_rows_per_input": size}
                for position, size in estimates
            ],
        }

    def _metric(self, node: Node, selection: dict[str, Any]) -> dict[str, Any]:
        key = (self.parent, id(node))
        metric = self._metrics.get(key)
        if metric is None:
            metric = {
                "operator": node.kind,
                "index": len(self.operators),
                "parent": self.parent,
                "calls": 0,
                "input_rows": 0,
                "output_rows": 0,
                "states": 0,
                "rows_examined": 0,
                "inclusive_ms": 0.0,
                "selection": selection,
            }
            if node.kind == "fact":
                metric.update(
                    relation=node.value.relation,
                    subject=node.value.subject,
                    object=node.value.object,
                    attributes=node.value.attrs,
                )
            self._metrics[key] = metric
            self.operators.append(metric)
        return metric

    def empty_relation(self, node: Node, input_rows: int) -> None:
        metric = self._metric(node, {
            "reason": "empty_relation",
            "estimated_rows_per_input": 0,
            "alternatives": [],
        })
        metric["calls"] += 1
        metric["input_rows"] += input_rows

    def run(
        self,
        engine: Executor,
        node: Node,
        spec: OperatorSpec,
        rows: list[Row],
        constraints: ScanConstraint | None,
        source: ScanConstraint | None,
    ) -> list[Row]:
        metric = self._metric(node, self.selection)
        if not metric["calls"]:
            predicates = getattr(constraints, "predicates", None)
            if node.kind == "fact" and predicates is not None:
                metric["property_prefilter"] = [
                    {"role": p.role, "attribute": p.attribute,
                     "other": p.other, "left": p.left, "literal": p.literal}
                    for p in predicates
                ]
            requirement = getattr(source, "owner", None)
            if requirement is not None:
                metric["source_prefilter"] = {
                    "owner": requirement.role,
                    "collection": requirement.place,
                    "required_relations": requirement.relations,
                }
                if hasattr(requirement, "names"):
                    metric["source_prefilter"]["call_names"] = requirement.names
                if hasattr(requirement, "kinds"):
                    metric["source_prefilter"]["operation_kinds"] = sorted(requirement.kinds)
        metric["calls"] += 1
        metric["input_rows"] += len(rows)
        parent, self.parent = self.parent, metric["index"]
        started, states, examined = time.perf_counter(), engine.states, engine.rows
        following: list[Row] = []
        try:
            for row in rows:
                engine.tick()
                spec.apply(engine, node, row, following, constraints)
        finally:
            # Inclusive costs include children and partially completed work.
            metric["output_rows"] += len(following)
            metric["states"] += engine.states - states
            metric["rows_examined"] += engine.rows - examined
            metric["inclusive_ms"] += (time.perf_counter() - started) * 1000
            self.parent = parent
        if source is not None and node.kind != "fact":
            started, before = time.perf_counter(), len(following)
            following = [row for row in following if source.allows(row.bindings)]
            removed = before - len(following)
            metric["candidate_rows_pruned"] = metric.get("candidate_rows_pruned", 0) + removed
            metric["output_rows"] -= removed
            metric["inclusive_ms"] += (time.perf_counter() - started) * 1000
        return following
