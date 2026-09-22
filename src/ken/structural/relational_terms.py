"""Comparison semantics shared by relational filters and join planning."""

from typing import Any

from .query import _compare as _base_compare


def compare(actual: Any, op: str, expected: str) -> bool:
    if op in ("literal", "not_literal"):
        equals = (
            "true" if actual is True else "false" if actual is False else str(actual)
        ) == expected
        return actual is not None and (equals if op == "literal" else not equals)
    return _base_compare(actual, op, expected)
