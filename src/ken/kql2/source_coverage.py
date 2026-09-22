"""Shared CFG coverage policy for BODY verification and safe scan pruning."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ken.structural.model import Fact

if TYPE_CHECKING:
    from .body import BodyPattern

_SUSPENSION = frozenset({"await", "await_expression"})
_ABRUPT_EXIT = frozenset({"raise_statement", "throw_statement"})
_YIELD = _SUSPENSION | {"yield", "yield_expression", "yield_statement"}


def _covered(statuses: Sequence[Fact], allowed: frozenset[str]) -> bool:
    return bool(statuses) and all(
        fact.object == "structured"
        or fact.object == "partial"
        and bool(fact.attrs.get("reasons"))
        and set(fact.attrs["reasons"]) <= allowed
        for fact in statuses
    )


def supports_general_walk(statuses: Sequence[Fact]) -> bool:
    """Await and abrupt exits preserve statement order for every BODY shape.

    Unknown reasons, empty inventories and yield scopes remain uncovered.
    Mixed statuses must all support the same coverage claim, as in BODY.
    """
    return _covered(statuses, _SUSPENSION) or _covered(statuses, _ABRUPT_EXIT)


def supports_pattern(statuses: Sequence[Fact], pattern: BodyPattern) -> bool:
    return supports_general_walk(statuses) or (
        len(pattern.clauses) == 1
        and pattern.clauses[0].kind == "yield"
        and _covered(statuses, _YIELD)
    )
