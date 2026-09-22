"""Pure join scheduling. Actions and BODY are optimization barriers."""

from __future__ import annotations

from .body import BodyPattern
from .compiler import KINDS, Action, Program, Scan

Step = Scan | Action | BodyPattern


def prepare(program: Program, *, reference: bool = False) -> tuple[Scan, ...]:
    """Bound-owner first, exact name before unfiltered domains; no count scans."""
    if program.steps:
        result: list[Scan] = []
        group: list[Scan] = []
        bound: set[str] = set()
        for step in program.steps:
            if isinstance(step, Scan):
                group.append(step)
            else:
                result.extend(_order_scans(tuple(group), bound, reference=reference))
                group.clear()
                if isinstance(step, BodyPattern):
                    bound.update(step.outputs)
                elif step.role:
                    bound.add(step.role)
        result.extend(_order_scans(tuple(group), bound, reference=reference))
        return tuple(result)
    return _order_scans(program.scans, set(), reference=reference)


def _order_scans(
    scans: tuple[Scan, ...], bound: set[str], *, reference: bool
) -> tuple[Scan, ...]:
    if reference:
        bound.update(s.role for s in scans)
        return scans
    remaining = list(scans)
    planned: list[Scan] = []
    while remaining:
        available = [s for s in remaining if s.owner is None or s.owner in bound]
        if not available:
            raise ValueError("cyclic scan binding dependencies")

        def score(scan: Scan) -> tuple[int, int]:
            return (
                0
                if scan.role in bound
                else 1
                if any(k == "name" and v.kind == "literal" for k, v in scan.properties)
                else 2
                if scan.owner
                else 3,
                len(KINDS.get(scan.selector, ())),
            )

        candidate = min(available, key=score)
        remaining.remove(candidate)
        planned.append(candidate)
        bound.add(candidate.role)
    return tuple(planned)


def schedule(program: Program, scans: tuple[Scan, ...]) -> tuple[Step, ...]:
    """Substitute ordered scans without moving any action or BODY boundary."""
    if not program.steps:
        return scans
    planned = iter(scans)
    return tuple(
        next(planned) if isinstance(step, Scan) else step for step in program.steps
    )


def explain(program: Program, *, reference: bool = False) -> list[dict[str, object]]:
    """Describe the physical schedule without a store or query execution."""
    if program.graph:
        return [{"operator": "relational_graph", "optimized": not reference}]
    if program.branches:
        return [
            {
                "operator": "union",
                "branches": [
                    explain(branch, reference=reference) for branch in program.branches
                ],
            }
        ]
    return [
        describe(step, reference=reference)
        for step in schedule(program, prepare(program, reference=reference))
    ]


def describe(step: Step, *, reference: bool) -> dict[str, object]:
    if isinstance(step, BodyPattern):
        return {
            "operator": "body",
            "owner": step.owner,
            "outputs": step.outputs,
            "barrier": True,
        }
    if isinstance(step, Action):
        return {
            "operator": "bind" if step.role else "filter",
            "role": step.role,
            "source": step.expression.span.source,
            "start": step.expression.span.start,
            "end": step.expression.span.end,
            "barrier": True,
        }
    access = (
        "reference_scan"
        if reference
        else "name_lookup"
        if any(
            key == "name" and value.kind == "literal" for key, value in step.properties
        )
        else "owner_lookup"
        if step.owner
        else "kind_scan"
    )
    return {
        "operator": "scan",
        "role": step.role,
        "selector": step.selector,
        "owner": step.owner,
        "access": access,
    }
