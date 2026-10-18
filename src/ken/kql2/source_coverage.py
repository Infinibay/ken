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
    # Existential source witnesses may follow normal resumption or one handler
    # route. Negative/all-path gaps still require the stronger general contract.
    route_witness = (all(clause.kind in {'call', 'let', 'return', 'yield'}
                         for clause in pattern.clauses)
                     and all(fact.attrs.get('language') == 'python' for fact in statuses)
                     and _covered(statuses, _YIELD | _ABRUPT_EXIT | {'exception-dispatch'}))
    local_gaps = bool(statuses) and all(
        fact.object == 'structured' or (
            fact.object == 'partial'
            and fact.attrs.get('analysis') == 'structured-cfg/2'
            and bool(fact.attrs.get('gaps'))
            and set(fact.attrs.get('reasons', ())) <= _YIELD | _ABRUPT_EXIT | {'try_statement', 'exception-dispatch'}
        ) for fact in statuses
    )
    return supports_general_walk(statuses) or route_witness or local_gaps or (
        len(pattern.clauses) == 1
        and pattern.clauses[0].kind == "yield"
        and _covered(statuses, _YIELD)
    )


def supports_normal_try(pattern: BodyPattern) -> bool:
    """Call/result witnesses can follow a try's modeled success path.

    Binding/field mutations still require the exceptional write inventory,
    which the statement CFG deliberately does not claim to model.
    """
    return all(clause.kind in {'call', 'let', 'return'} for clause in pattern.clauses)
