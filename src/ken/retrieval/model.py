"""Code identity and source evidence, independent of database row identifiers."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class Span:
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if not 1 <= self.start_line <= self.end_line:
            raise ValueError("invalid inclusive source span")

    def to_dict(self) -> dict[str, int]:
        return {"start_line": self.start_line, "end_line": self.end_line}


@dataclass(frozen=True)
class EntityKey:
    path: str
    kind: str
    qualname: str | None
    owner: str | None = None
    definition_ordinal: int = 0

    def to_dict(self) -> dict[str, str | int | None]:
        return {"kind": self.kind, "qualname": self.qualname,
                "owner": self.owner, "definition_ordinal": self.definition_ordinal}


@dataclass(frozen=True)
class Passage:
    entity: EntityKey
    span: Span
    fields: dict[str, str]
    source_hash: str
    entity_span: Span
    language: str = "text"
    role: str = "definition"
    split_reason: str | None = None
    signals: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchRequest:
    query: str
    target: str = "symbol"
    purpose: str = "auto"
    limit: int = 10
    max_chars: int = 12000
    explain: bool = False

    def __post_init__(self) -> None:
        if not self.query.strip() or self.limit <= 0 or self.max_chars <= 0:
            raise ValueError("query and positive result/output budgets required")
        if self.target not in ("file", "symbol", "passage"):
            raise ValueError("unknown search target")
        if self.purpose not in ("auto", "implementation", "usage", "tests", "documentation"):
            raise ValueError("unknown search purpose")


@dataclass
class Candidate:
    entity: EntityKey
    passages: list[Passage]
    signals: dict[str, float] = field(default_factory=dict)
