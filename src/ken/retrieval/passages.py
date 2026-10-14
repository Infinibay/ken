"""Partition source within its narrowest proven owner; never invent source text."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from ken.parsers.types import ParsedFile, ParsedScope
from ken.retrieval.model import EntityKey, Passage, Span

EXTRACTOR_VERSION = 3


def lexical_token_count(text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE))


@dataclass(frozen=True)
class PassagePolicy:
    max_tokens: int = 256
    count_tokens: Callable[[str], int] = lexical_token_count
    tokenizer_version: str = "code-lexical-v1"

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")


def _role(path: str, name: str | None) -> str:
    parts = {p.lower() for p in PurePosixPath(path).parts}
    stem = PurePosixPath(path).stem.lower()
    if parts & {"tests", "test", "__tests__"} or stem.startswith("test_") or (name or "").startswith("test_"):
        return "test"
    if parts & {"examples", "example", "demo", "demos"}:
        return "example"
    if parts & {"docs", "doc", "documentation"}:
        return "documentation"
    return "definition"


def extract_passages(source: bytes, parsed: ParsedFile, *, path: str,
                     policy: PassagePolicy | None = None,
                     language: str = "text") -> list[Passage]:
    policy = policy or PassagePolicy()
    if b"\x00" in source:
        return []
    lines = source.decode("utf-8", errors="replace").splitlines()
    if not lines:
        return []
    digest = hashlib.sha256(source).hexdigest()
    scopes = list(parsed.scopes)
    if not scopes:
        for symbol in parsed.symbols:
            owner = symbol.qualname.rsplit(".", 1)[0] if "." in symbol.qualname else None
            scopes.append(ParsedScope(symbol=symbol, owner=owner,
                signature=lines[symbol.line_start - 1], documentation=symbol.docstring))
    scopes.sort(key=lambda s: (s.symbol.line_start, -s.symbol.line_end))
    assigned: dict[int, int] = {}
    # Shorter scopes own their nested source lines; parent bodies do not duplicate them.
    for index in sorted(range(len(scopes)),
                        key=lambda i: scopes[i].symbol.line_end - scopes[i].symbol.line_start):
        symbol = scopes[index].symbol
        for line in range(symbol.line_start, min(symbol.line_end, len(lines)) + 1):
            assigned.setdefault(line, index)
    ordinals: dict[tuple[str, str, str | None], int] = defaultdict(int)
    identities: dict[int, EntityKey] = {}
    for index, scope in enumerate(scopes):
        s = scope.symbol
        group = (s.kind, s.qualname, scope.owner)
        identities[index] = EntityKey(path, s.kind, s.qualname, scope.owner, ordinals[group])
        ordinals[group] += 1
    identities[-1] = EntityKey(path, "module", None)
    out: list[Passage] = []
    start = 1
    while start <= len(lines):
        owner_index = assigned.get(start, -1)
        owner_scope = scopes[owner_index] if owner_index >= 0 else None
        implementation_start = owner_scope.implementation_start_line if owner_scope else None
        statement_ends = {end for _, end in owner_scope.statements} if owner_scope else set()
        end = start
        while end < len(lines) and assigned.get(end + 1, -1) == owner_index:
            if end + 1 == implementation_start:
                break
            candidate = "\n".join(lines[start - 1:end + 1])
            if policy.count_tokens(candidate) > policy.max_tokens:
                break
            end += 1
        if (end < len(lines) and assigned.get(end + 1, -1) == owner_index
                and end + 1 != implementation_start):
            boundary = max((line for line in statement_ends if start <= line <= end), default=end)
            end = boundary
        body = "\n".join(lines[start - 1:end])
        if body.strip():
            current_scope = scopes[owner_index] if owner_index >= 0 else None
            entity = identities[owner_index]
            fields = {"identity": " ".join(x for x in
                         (entity.kind, entity.qualname, entity.owner) if x),
                      "signature": current_scope.signature if current_scope else "",
                      "documentation": (current_scope.documentation or "") if current_scope else (parsed.docstring or ""),
                      "body": body, "path": path}
            extent = Span(current_scope.symbol.line_start, current_scope.symbol.line_end) if current_scope else Span(1, len(lines))
            split = "oversized_line" if policy.count_tokens(body) > policy.max_tokens else None
            out.append(Passage(entity, Span(start, end), fields, digest, extent,
                               language, _role(path, entity.qualname), split,
                               implementation_start_line=implementation_start))
        start = end + 1
    return out
