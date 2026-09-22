"""Cooperative execution limits and snapshot lifetime, independent of operators."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from ken.structural_store import Store
from ken.structural_store.leases import SnapshotExpired, renew

from .outcome import Outcome


class ExecutionStopped(Exception):
    """Internal control flow; the public outcome carries the stop reason."""


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    timeout_ms: float | None = None
    max_states: int | None = None
    max_rows: int | None = None

    def __post_init__(self) -> None:
        if (
            self.timeout_ms is not None
            and (not math.isfinite(self.timeout_ms) or self.timeout_ms < 0)
            or self.max_states is not None
            and self.max_states < 1
            or self.max_rows is not None
            and self.max_rows < 1
        ):
            raise ValueError("invalid execution budget")


class ExecutionControl:
    def __init__(
        self,
        store: Store,
        result: Outcome,
        budget: ExecutionBudget,
        started: float,
        cancelled: Callable[[], bool] | None,
    ):
        self.store, self.result, self.budget = store, result, budget
        self.cancelled = cancelled
        self.deadline = (
            started + budget.timeout_ms / 1000
            if budget.timeout_ms is not None
            else math.inf
        )

    def stop(self, reason: str) -> None:
        self.result.reason = reason
        raise ExecutionStopped

    def check(self) -> None:
        try:
            renew(self.store)
        except SnapshotExpired:
            self.stop("snapshot_expired")
        self.result.states += 1
        if self.cancelled and self.cancelled():
            self.stop("cancelled")
        if time.monotonic() >= self.deadline:
            self.stop("timeout")
        if (
            self.budget.max_states is not None
            and self.result.states > self.budget.max_states
        ):
            self.stop("max_states")
