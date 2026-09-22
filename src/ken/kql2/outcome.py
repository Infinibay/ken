"""Execution results shared by the indexed and relational graph backends."""

from __future__ import annotations

from dataclasses import dataclass, field

from .values import QueryValue


@dataclass
class Outcome:
    rows: list[tuple[QueryValue, ...]] = field(default_factory=list)
    complete: bool = True
    results_truncated: bool = False
    unknown_candidates: int = 0
    reason: str | None = None
    scanned_nodes: int = 0
    states: int = 0
    elapsed_ms: float = 0
    plan: list[dict[str, object]] = field(default_factory=list)
    optional_evidence: list[dict[str, object]] = field(default_factory=list)
    order_keys: list[tuple[QueryValue, ...]] = field(default_factory=list)
    profile: list[dict[str, object]] = field(default_factory=list)
