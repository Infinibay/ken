"""Quote selected lexical context without relabeling its canonical source owners."""
from __future__ import annotations

from collections.abc import Sequence
import hashlib
from typing import Any

from ken.retrieval.model import EntityKey, Span
from lexical_context import LexicalContext


def context_fragments(context: LexicalContext, source: bytes, spans: Sequence[Span], *,
                      primary: EntityKey, generation: str, max_lines: int = 40,
                      max_fragments: int = 3) -> list[dict[str, Any]]:
    """Render a selection from an independently registered context catalog.

    The caller must bind the catalog's receipt to the active source snapshot.
    This consumer checks physical freshness and selection boundaries; it does
    not recreate AST proof or infer runtime behavior. JSON response budgeting
    and query-based selection are separate responsibilities, not performed here.
    Call again with final trimmed spans so metadata quotes only visible lines.
    """
    if (not generation or context.generation != generation or context.primary != primary
            or hashlib.sha256(source).hexdigest() != context.source_hash):
        raise ValueError('context selection identity, generation or source is stale')
    if not 1 <= max_lines <= 40 or not 1 <= max_fragments <= 3:
        raise ValueError('context selection cannot exceed the fixed source budgets')
    selected = sorted(spans)
    if (not selected or len(selected) > max_fragments
            or sum(s.end_line-s.start_line+1 for s in selected) > max_lines
            or any(a.end_line >= b.start_line for a,b in zip(selected, selected[1:]))
            or any(s.start_line < context.extent.start_line or s.end_line > context.extent.end_line
                   for s in selected)):
        raise ValueError('context selection leaves its proven extent or budget')
    lines = source.decode('utf-8').splitlines()
    if context.extent.end_line > len(lines):
        raise ValueError('context extent leaves physical source')
    owners: dict[int, EntityKey | None] = {}
    for part in context.parts:
        if (part.owner is not None and part.owner.path != primary.path
                or source[part.start_byte:part.end_byte].decode('utf-8') != part.text):
            raise ValueError('context provenance differs from its physical source')
        for line in range(part.span.start_line, part.span.end_line+1):
            if line in owners:
                raise ValueError('context provenance overlaps')
            owners[line] = part.owner
    if set(owners) != set(range(context.extent.start_line, context.extent.end_line+1)):
        raise ValueError('context provenance is incomplete')
    fragments: list[dict[str, Any]] = []
    for span in selected:
        visible_owners: list[dict[str, Any]] = []
        for part in context.parts:
            start = max(span.start_line, part.span.start_line)
            end = min(span.end_line, part.span.end_line)
            if start <= end:
                visible_owners.append({'start_line': start, 'end_line': end,
                    'entity': part.owner.to_dict() if part.owner is not None else None})
        fragments.append({'start_line': span.start_line, 'end_line': span.end_line,
            'content': '\n'.join(lines[span.start_line-1:span.end_line]),
            'source_owners': visible_owners})
    return fragments
