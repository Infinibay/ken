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
