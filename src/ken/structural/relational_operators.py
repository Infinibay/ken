"""Relational operator strategies and their optimization boundaries.

Handlers append to the caller's output batch to avoid an allocation per input row.
The registry is immutable; operator execution and barrier metadata live together.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from .query import _bind, _Exhausted, _resolve
from .relational_ir import Node, Row, ScanConstraint
from .relational_terms import compare as _compare
from .relational_evidence import ProofAccumulator, materialize

if TYPE_CHECKING:
    from .relational import Executor


def apply_fact(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    following.extend(engine.facts(node.value, row, scan_constraints))


def apply_fact_union(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    for clause in node.value:
        following.extend(engine.facts(clause, row, scan_constraints))


def apply_where(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    a, op, b = node.value
    left, right = engine.operand(a, row), engine.operand(b, row)
    if left is None or right is None:
        following.append(
            Row(row.bindings, row.evidence, row.unknown | {"attribute:missing"})
        )
    elif _compare(left, "=" if op == "==" else op, str(right)):
        following.append(row)


def apply_different(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    if row.bindings[node.value[0]] != row.bindings[node.value[1]]:
        following.append(row)


def apply_source_receiver(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    owner_role, receiver_role = node.value
    owner = row.bindings[owner_role]
    for member in engine.index.rows("HAS_METHOD", object=owner):
        engine.tick()
        if member.object != owner:
            continue
        entity = engine.index.ir.entities.get(owner)
        if entity is not None and entity.attrs.get("static"):
            continue
        for receiver in engine.index.rows("INSTANCE_RECEIVER", member.subject):
            engine.tick()
            if receiver.subject != member.subject:
                continue
            if (
                receiver_role in row.bindings
                and row.bindings[receiver_role] != receiver.object
            ):
                continue
            following.append(
                Row(
                    {**row.bindings, receiver_role: receiver.object},
                    row.evidence,
                    row.unknown,
                )
            )


def apply_source_quantifier(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.source_quantifiers import match

    following.extend(match(engine, node.value, row))


def apply_source_usages(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.source_usages import match

    following.extend(match(engine, node.value, row))


def apply_source_initializer(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.declaration_initializers import match

    following.extend(match(engine, node.value, row))


def apply_source_effective_field(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.effective_fields import match

    following.extend(match(engine, node.value, row))


def apply_source_type(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.source_type_filter import filter_row

    following.extend(filter_row(engine, node.value, row))


def apply_source_body(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    from ken.kql2.source_execution import SourceExecutor

    if engine._source_executor is None:
        engine._source_executor = SourceExecutor(engine)
    following.extend(engine._source_executor.match(node.value, row))


def apply_any(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    for branch in node.children:
        following.extend(engine.run_nodes(branch, [row]))


def apply_match(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    name, bindings, proof = node.value
    child = engine.queries[name]
    seed = {
        child.exports[k]: row.bindings[v]
        for k, v in bindings.items()
        if v in row.bindings
    }
    key = (name, engine.scope, tuple(sorted(seed.items())))
    if key not in engine.cache:
        engine.cache[key] = engine.run_nodes(child.nodes, [Row(seed)])
    engine.dependencies.add(name)
    matched_rows: dict[tuple, ProofAccumulator] = {}
    for hit in engine.cache[key]:
        b = dict(row.bindings)
        accepted = True
        for role, target in bindings.items():
            value = hit.bindings[child.exports[role]]
            if target in b and b[target] != value:
                accepted = False
                break
            b[target] = value
        identity = tuple(sorted(b.items()))
        if accepted:
            if proof:
                b[proof] = json.dumps(materialize(hit.evidence), sort_keys=True)
            match_row = Row(
                b,
                row.evidence
                + [{"query": name, "proof": proof, "evidence": hit.evidence}],
                row.unknown | hit.unknown,
            )
            old = matched_rows.get(identity)
            if old is None:
                matched_rows[identity] = ProofAccumulator(match_row)
            else:
                old.add(match_row)
    following.extend(proofs.finish() for proofs in matched_rows.values())


def apply_scoped(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    previous_scope = engine.scope
    if node.kind == "not":
        engine.scope = row.bindings[node.value[1]]
    try:
        hits = engine.run_nodes(node.children[0], [row])
    finally:
        engine.scope = previous_scope
    if node.kind == "optional":
        following.append(
            Row(
                row.bindings,
                row.evidence + [{"optional": h.evidence} for h in hits],
                row.unknown,
            )
        )
    elif node.kind == "not":
        certain = [h for h in hits if h.unknown <= row.unknown]
        if not certain:
            missing = set(row.unknown)
            if hits or not engine.closed(
                node.children[0], row, row.bindings[node.value[1]]
            ):
                missing.add(f"absence:{node.value[0]}:{row.bindings[node.value[1]]}")
            following.append(Row(row.bindings, row.evidence, missing))
    else:
        role, op, num = node.value
        count = len({h.bindings[role] for h in hits if h.unknown <= row.unknown})
        # Lower bounds can be established by witnesses. Exact/upper
        # counts need relation-scoped closure, never global syntax.
        if _compare(count, op, str(num)):
            missing = set(row.unknown)
            if op in {"=", "<=", "<"} and not engine.closed(node.children[0], row):
                missing.add("cardinality:open_world")
            following.append(Row(row.bindings, row.evidence, missing))
        elif not engine.closed(node.children[0], row):
            following.append(
                Row(
                    row.bindings, row.evidence, row.unknown | {"cardinality:open_world"}
                )
            )


def apply_path(
    engine: Executor,
    node: Node,
    row: Row,
    following: list[Row],
    scan_constraints: ScanConstraint | None,
) -> None:
    a, rel, b, lo, hi, proof = node.value
    resolved_start = _resolve(a, row.bindings)
    starts = (
        [resolved_start]
        if resolved_start is not None
        else sorted(
            set(engine.index.ir.entities)
            | {f.subject for f in engine.index.rows(rel)}
            | {f.object for f in engine.index.rows(rel)}
        )
    )
    for start in starts:
        frontier: list[tuple[str, list[str], set[str]]] = [(start, [], set())]
        seen_targets: set[tuple[str, bool]] = set()
        for depth in range(hi + 1):
            nxt = []
            # This path operator exposes the first witness for an
            # endpoint/modality, not every walk. At a given depth,
            # convergent walks have identical future reachability.
            # Keep depths separate: a cycle may satisfy a lower
            # bound that its earlier visit did not satisfy.
            next_states: set[tuple[str, bool]] = set()
            for target, witness, path_unknown in frontier:
                engine.tick()
                if depth >= lo and (target, bool(path_unknown)) not in seen_targets:
                    seen_targets.add((target, bool(path_unknown)))
                    if b not in row.bindings or row.bindings[b] == target:
                        bindings = dict(row.bindings)
                        if _bind(a, start, bindings) and _bind(b, target, bindings):
                            bindings[proof] = json.dumps([start] + witness)
                            following.append(
                                Row(
                                    bindings,
                                    row.evidence
                                    + [{"path": rel, "nodes": [start] + witness}],
                                    row.unknown | path_unknown,
                                )
                            )
                if depth < hi:
                    for f in engine.index.rows(rel, target):
                        engine.rows += 1
                        if (
                            engine.budget.max_rows is not None
                            and engine.rows > engine.budget.max_rows
                        ):
                            raise _Exhausted("max_rows")
                        uncertainty = path_unknown | (
                            {"possible:" + rel}
                            if f.attrs.get("modality") == "may"
                            else set()
                        )
                        state = (f.object, bool(uncertainty))
                        if state not in next_states:
                            next_states.add(state)
                            nxt.append((f.object, witness + [f.object], uncertainty))
            frontier = nxt


Handler = Callable[["Executor", Node, Row, list[Row], ScanConstraint | None], None]


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    apply: Handler
    barrier: bool = True
    clears_scan_constraints: bool = False
    # An extension must opt in before absence can count as proof. Source
    # operators describe witnesses, not complete inventories.
    preserves_closure: bool = False


OPERATORS: Mapping[str, OperatorSpec] = MappingProxyType(
    {
        "fact": OperatorSpec(apply_fact, barrier=False, preserves_closure=True),
        "where": OperatorSpec(apply_where, barrier=False, preserves_closure=True),
        "different": OperatorSpec(apply_different, barrier=False, preserves_closure=True),
        "source_receiver": OperatorSpec(apply_source_receiver),
        "source_quantifier": OperatorSpec(apply_source_quantifier),
        "source_usages": OperatorSpec(apply_source_usages),
        "source_initializer": OperatorSpec(apply_source_initializer),
        "source_effective_field": OperatorSpec(apply_source_effective_field),
        "source_type": OperatorSpec(apply_source_type),
        "source_body": OperatorSpec(apply_source_body, clears_scan_constraints=True),
        "any": OperatorSpec(apply_any, preserves_closure=True),
        "fact_union": OperatorSpec(apply_fact_union, barrier=False, preserves_closure=True),
        "match": OperatorSpec(apply_match, preserves_closure=True),
        "count": OperatorSpec(apply_scoped, preserves_closure=True),
        "not": OperatorSpec(apply_scoped, preserves_closure=True),
        "optional": OperatorSpec(apply_scoped, preserves_closure=True),
        "path": OperatorSpec(apply_path, preserves_closure=True),
    }
)
