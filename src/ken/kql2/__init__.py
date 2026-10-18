"""KQL 2 frontend. Parsing does not imply that an analysis is implemented."""
from typing import TYPE_CHECKING, Any

from .syntax import ParseError, parse

if TYPE_CHECKING:
    from .session import QuerySession

__all__ = ["ParseError", "parse", "QuerySession"]


def __getattr__(name: str) -> Any:
    if name == "QuerySession":
        from .session import QuerySession

        return QuerySession
    raise AttributeError(name)
