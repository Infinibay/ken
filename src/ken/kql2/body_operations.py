"""The operation inventory a BODY clause may inspect.

The matcher and the scan planner share this contract. A finite kind set is a
necessary condition, not evidence that the clause matches. Indexed callees can
also be accredited by semantic occurrences under another syntax kind.
"""

from dataclasses import dataclass
from types import MappingProxyType

from .syntax import Clause


@dataclass(frozen=True)
class OperationFilter:
    kinds: frozenset[str] | None = None
    semantic_calls: bool = False


_ANY = OperationFilter()
_CALL = OperationFilter(frozenset({"CALL"}))
_WRITE = OperationFilter(frozenset({"ASSIGN", "UPDATE"}))
_COLLECTION_WRITE = OperationFilter(frozenset({"CALL", "ASSIGN", "UPDATE"}))
_INDEXED_CALL = OperationFilter(_CALL.kinds, semantic_calls=True)
_FILTERS = MappingProxyType({
    "call": _CALL,
    "let": _CALL,
    "assign": _WRITE,
    "return": OperationFilter(frozenset({"RETURN"})),
    "yield": OperationFilter(frozenset({"YIELD"})),
    "if": OperationFilter(frozenset({"BRANCH"})),
    "iterate": OperationFilter(frozenset({"LOOP"})),
    "insert": _COLLECTION_WRITE,
    "clear": _COLLECTION_WRITE,
})


def operation_filter(clause: Clause) -> OperationFilter:
    """Describe candidates without resolving roles or evaluating expressions."""
    if clause.kind in {"let", "call"} and clause.expressions:
        if clause.expressions[0].kind == "index":
            return _WRITE if clause.kind == "let" else _INDEXED_CALL
    return _FILTERS.get(clause.kind, _ANY)
