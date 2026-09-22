"""The question, source facts, and contributions shared by responsibility reasoners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Symbol:
    path: str
    qualname: str
    kind: str
    line: int
    end_line: int
    documentation: str
    sha256: str
    calls: tuple[tuple[str, int], ...] = ()
    refreshed: bool = False
    doc_scope: str = "full"


@dataclass(frozen=True)
class Evidence:
    reasoner: str
    direction: Literal["supports", "against", "context"]
    strength: float
    explanation: str
    assumption: str = ""


@dataclass(frozen=True)
class Inquiry:
    wording: str
    terms: frozenset[str]
    similarity: float


class Reasoner(Protocol):
    """Assess one responsibility against one live symbol; never select a winner."""

    def assess(self, inquiry: Inquiry, symbol: Symbol) -> tuple[Evidence, ...]: ...
