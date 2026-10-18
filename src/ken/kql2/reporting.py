"""Public KQL2 result fields independent of acquisition and cache policy."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import Program
    from .outcome import Outcome


def serialize_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return serialize_value(asdict(value))
    if isinstance(value, (list, tuple)):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {key: serialize_value(v) for key, v in value.items()}
    return value


def query_response(program: Program, outcome: Outcome, coverage: bool) -> dict[str, Any]:
    return {
        "language": "kql/2",
        "capability": "structural-source/1",
        "query": program.name,
        "columns": [expr.value or f"column_{i + 1}" for i, expr in enumerate(program.projection)],
        "rows": [[serialize_value(v) for v in row] for row in outcome.rows],
        "complete": outcome.complete,
        "coverage_complete": coverage,
        "unknown_candidates": outcome.unknown_candidates,
        "reason": outcome.reason,
        "results_truncated": outcome.results_truncated,
        "plan": outcome.plan,
        "optional_evidence": outcome.optional_evidence,
    }
