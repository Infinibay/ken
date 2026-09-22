"""KQL2 execution facade: backend selection, streaming plans and result assembly."""

from __future__ import annotations

import time
from collections.abc import Callable

from ken.structural_store import Node, Store

from .compiler import Program, Scan
from .execution_control import ExecutionBudget, ExecutionControl, ExecutionStopped
from .operators import build_operator
from .outcome import Outcome
from .pipeline import OperatorStats, run
from .planning import describe, prepare, schedule
from .runtime import QueryRuntime
from .values import (
    ASTValue,
    EnumValue,
    OperationValue,
    QueryValue,
    identity,
    is_unknown,
)

Value = QueryValue
__all__ = ["Outcome", "Value", "execute", "prepare"]


def execute(
    program: Program,
    store: Store,
    snapshot: int,
    *,
    reference: bool = False,
    timeout_ms: float | None = None,
    max_states: int | None = None,
    max_rows: int | None = None,
    cancelled: Callable[[], bool] | None = None,
    prepared_plans: dict[str, tuple[Scan, ...]] | None = None,
    profile: bool = False,
) -> Outcome:
    """Execute a compiled query; profiling is opt-in and does not change budgets."""
    started = time.monotonic()
    budget = ExecutionBudget(timeout_ms, max_states, max_rows)
    if program.graph:
        from .graph_execution import execute_graph

        return execute_graph(
            program,
            store,
            snapshot,
            reference=reference,
            timeout_ms=timeout_ms,
            max_states=max_states,
            max_rows=max_rows,
            cancelled=cancelled,
            profile=profile,
        )
    if program.branches:
        return _execute_union(
            program,
            store,
            snapshot,
            reference=reference,
            timeout_ms=timeout_ms,
            max_states=max_states,
            max_rows=max_rows,
            cancelled=cancelled,
            prepared_plans=prepared_plans,
            profile=profile,
            started=started,
        )
    return _execute_indexed(
        program,
        store,
        snapshot,
        reference=reference,
        budget=budget,
        cancelled=cancelled,
        prepared_plans=prepared_plans,
        profile=profile,
        started=started,
    )


def _execute_indexed(
    program: Program,
    store: Store,
    snapshot: int,
    *,
    reference: bool,
    budget: ExecutionBudget,
    cancelled: Callable[[], bool] | None,
    prepared_plans: dict[str, tuple[Scan, ...]] | None,
    profile: bool,
    started: float,
) -> Outcome:
    initial_scanned = store.scanned
    result = Outcome()
    control = ExecutionControl(store, result, budget, started, cancelled)
    runtime = QueryRuntime(program, store, snapshot, control, reference=reference)
    scans = (
        prepared_plans[program.fingerprint]
        if prepared_plans is not None
        else prepare(program, reference=reference)
    )
    steps = schedule(program, scans)
    operators = tuple(build_operator(step, runtime) for step in steps)
    stats = tuple(OperatorStats() for _ in steps) if profile else ()
    result.plan = [describe(step, reference=reference) for step in steps]
    materialized: list[tuple[tuple[Value, ...], tuple[Value, ...]]] = []
    seen: set[object] = set()
    remaining_actions = (
        ()
        if program.steps
        else program.actions or tuple(("", f) for f in program.filters)
    )
    frames = run(operators, control.check, stats)
    try:
        for frame in frames:
            control.check()
            computed = dict(frame.bindings)
            uncertain = frame.uncertain
            passed = True
            for role, condition in remaining_actions:
                truth = runtime.evaluate(condition, computed)
                if role:
                    computed[role] = truth
                    continue
                if truth is False:
                    passed = False
                    break
                uncertain |= is_unknown(truth)
            if not passed:
                continue
            row = tuple(
                runtime.evaluate(e.args[0], computed) for e in program.projection
            )
            order = tuple(
                runtime.evaluate(e.args[0], computed) for e in program.ordering
            )
            if uncertain or any(is_unknown(value) for value in row + order):
                result.unknown_candidates += 1
                continue
            row_key = identity(row)
            if row_key not in seen:
                if budget.max_rows is not None and len(materialized) >= budget.max_rows:
                    control.stop("max_rows")
                seen.add(row_key)
                materialized.append((row, order))
            for optional in program.optional:
                truth = runtime.evaluate(optional, computed)
                result.optional_evidence.append(
                    {
                        "source": optional.span.source,
                        "start": optional.span.start,
                        "end": optional.span.end,
                        "status": "unknown"
                        if is_unknown(truth)
                        else "matched"
                        if truth is True
                        else "absent",
                        "bindings": {
                            name: node.id if isinstance(node, Node) else repr(node)
                            for name, node in frame.bindings.items()
                        },
                    }
                )
    except TimeoutError:
        result.reason, result.complete = "regex_timeout", False
    except ExecutionStopped:
        result.complete = False
    except RecursionError:
        result.reason, result.complete = "evaluation_depth", False
    finally:
        frames.close()
    _finish(result, materialized, program)
    if profile:
        result.profile = [
            {**describe(step, reference=reference), "index": index, **metric.as_dict()}
            for index, (step, metric) in enumerate(zip(steps, stats))
        ]
    result.scanned_nodes = store.scanned - initial_scanned
    result.elapsed_ms = (time.monotonic() - started) * 1000
    return result


def _finish(
    result: Outcome,
    rows: list[tuple[tuple[Value, ...], tuple[Value, ...]]],
    program: Program,
) -> None:
    for position in reversed(range(len(program.ordering))):
        rows.sort(
            key=lambda item: _order_value(item[1][position]),
            reverse=program.ordering[position].value == "desc",
        )
    result.rows = [row for row, _ in rows]
    result.order_keys = [key for _, key in rows]
    if program.limit is not None:
        result.results_truncated = len(result.rows) > program.limit
        result.rows = result.rows[: program.limit]
        result.order_keys = result.order_keys[: program.limit]


def _execute_union(
    program: Program,
    store: Store,
    snapshot: int,
    *,
    reference: bool,
    timeout_ms: float | None,
    max_states: int | None,
    max_rows: int | None,
    cancelled: Callable[[], bool] | None,
    prepared_plans: dict[str, tuple[Scan, ...]] | None,
    profile: bool,
    started: float,
) -> Outcome:
    union = Outcome()
    seen_rows: set[object] = set()
    for branch_index, branch in enumerate(program.branches):
        if max_states is not None and union.states >= max_states:
            union.complete, union.reason = False, "max_states"
            break
        remaining_ms = (
            max(0, timeout_ms - (time.monotonic() - started) * 1000)
            if timeout_ms is not None
            else None
        )
        child = execute(
            branch,
            store,
            snapshot,
            reference=reference,
            timeout_ms=remaining_ms,
            max_states=max(1, max_states - union.states)
            if max_states is not None
            else None,
            max_rows=max_rows,
            cancelled=cancelled,
            prepared_plans=prepared_plans,
            profile=profile,
        )
        union.complete &= child.complete
        union.reason = union.reason or child.reason
        union.unknown_candidates += child.unknown_candidates
        union.scanned_nodes += child.scanned_nodes
        union.states += child.states
        union.plan.extend(child.plan)
        union.profile.extend(
            {**entry, "branch": branch.name, "branch_index": branch_index}
            for entry in child.profile
        )
        union.optional_evidence.extend(child.optional_evidence)
        for row, order_key in zip(child.rows, child.order_keys):
            row_key = identity(row)
            if row_key not in seen_rows:
                if max_rows is not None and len(union.rows) >= max_rows:
                    union.complete, union.reason = False, "max_rows"
                    break
                seen_rows.add(row_key)
                union.rows.append(row)
                union.order_keys.append(order_key)
        if not union.complete:
            break
    _finish(union, list(zip(union.rows, union.order_keys)), program)
    union.elapsed_ms = (time.monotonic() - started) * 1000
    return union


def _order_value(value: Value) -> tuple[str, str | int | float]:
    if isinstance(value, (Node, OperationValue, ASTValue)):
        return "Entity", value.path + ":" + value.local_id
    if isinstance(value, EnumValue):
        return "Enum", value.type + "." + value.name
    if isinstance(value, (str, int, float)):
        return type(value).__name__, value
    return "Null", ""
