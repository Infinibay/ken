"""Offline relevance targets for owners, independent of visible answer grading.

This predicate asks whether an owner's available source *can* satisfy a
reference. It does not claim that the search response actually exposed it;
the unchanged response evaluator owns that separate check.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from ken.bench.dataset import Record
from ken.bench.retrieval import _identity
from ken.retrieval.model import EntityKey, Span, merge_spans


def eligible_owner(entity: EntityKey, source_hash: str, regions: Iterable[Span],
                   alternatives: Sequence[Record]) -> bool:
    """Require identity, current bytes, and every anchor of one alternative."""
    owned = merge_spans(regions)
    record = {'path': entity.path, 'entity': entity.to_dict()}
    return any(
        _identity(record, alternative)
        and source_hash == alternative['source_hash']
        and all(any(region.start_line <= anchor['start_line']
                    and anchor['end_line'] <= region.end_line for region in owned)
                for anchor in alternative['anchors'])
        for alternative in alternatives
    )
