"""KQL 2 frontend. Parsing does not imply that an analysis is implemented."""
from .syntax import ParseError, parse

__all__ = ["ParseError", "parse"]
