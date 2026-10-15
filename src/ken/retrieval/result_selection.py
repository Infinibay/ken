"""Choose which ranked owners can occupy result slots before character trimming."""
from __future__ import annotations

from collections.abc import Iterator, Sequence

from ken.retrieval.model import CodeMatch, SearchRequest


def displayed_matches(matches: Sequence[CodeMatch], request: SearchRequest
                      ) -> Iterator[tuple[int, CodeMatch]]:
    seen_files: set[str] = set()
    shown = 0
    for index, match in enumerate(matches):
        if request.target == 'file' and match.entity.path in seen_files:
            continue
        if shown >= request.limit:
            break
        seen_files.add(match.entity.path)
        shown += 1
        yield index, match
