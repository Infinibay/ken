"""Source-owned occurrences of declaration names, with no call-target inference."""
from __future__ import annotations

import re
from collections.abc import Sequence

from ken.retrieval.model import EntityKey, Passage

_IDENTIFIER = re.compile(r'[\w$]+')


def declaration_name(entity: EntityKey) -> str | None:
    """Project a canonical declaration to its literal bare spelling."""
    if entity.qualname is None:
        return None
    name = re.split(r'\.|::', entity.qualname)[-1]
    return name if _IDENTIFIER.fullmatch(name) else None


def mentioned_names(passages: Sequence[Passage], known: frozenset[str]
                    ) -> tuple[tuple[str, int], ...]:
    """Keep the first owned source line for each spelling, including non-calls.

    A posting does not resolve overloads, bindings, receivers or runtime targets.
    Comments, strings and other declarations can all supply literal context.
    Disjoint source regions are scanned separately, never concatenated as words.
    """
    first: dict[str, int] = {}
    for passage in passages:
        lines = passage.fields['body'].splitlines()
        if len(lines) > passage.span.end_line-passage.span.start_line+1:
            raise ValueError('name context body extends beyond its owned source span')
        for line_number, line in enumerate(lines, start=passage.span.start_line):
            for match in _IDENTIFIER.finditer(line):
                name = match[0]
                if name in known:
                    first[name] = min(first.get(name, line_number), line_number)
    return tuple(sorted(first.items()))
