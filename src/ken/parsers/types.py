"""Shared dataclasses returned by every language parser."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedSymbol:
    kind: str          # function | class | method | const | …
    name: str
    qualname: str
    line_start: int    # 1-based
    line_end: int      # 1-based, inclusive
    docstring: str | None = None


@dataclass
class ParsedImport:
    module: str
    line: int


@dataclass
class ParsedFile:
    """Result of parsing one source file."""

    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    docstring: str | None = None
