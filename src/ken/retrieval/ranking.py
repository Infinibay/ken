"""Baseline entity ordering; scores are ranking evidence, never confidence."""
from __future__ import annotations

from ken.retrieval.model import Candidate, CodeMatch, SearchRequest


def rank_candidates(request: SearchRequest, candidates: list[Candidate]) -> list[CodeMatch]:
    ordered = sorted(candidates, key=lambda c: (
        -c.signals.get("exact", 0), -c.signals.get("rrf", 0),
        c.entity.path, min(p.span.start_line for p in c.passages)))
    return [CodeMatch(c.entity, c.signals.get("rrf", 0.0), c.passages,
                      c.passages[0].source_hash, dict(c.signals)) for c in ordered]
