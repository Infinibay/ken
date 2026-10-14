"""One explicit search path: retrieve, order entities, then expose current evidence."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ken.retrieval.candidates import active_profile, retrieve
from ken.retrieval.model import SearchRequest, SearchResponse
from ken.retrieval.presentation import present
from ken.retrieval.evidence import refine_evidence
from ken.retrieval.profile import Encoder, RetrievalProfile
from ken.retrieval.ranking import RelevanceJudge, rank_candidates


def search(conn: sqlite3.Connection, root: Path, request: SearchRequest, *,
           profile: RetrievalProfile | None = None,
           encoders: Mapping[str, Encoder] | None = None,
           judge: RelevanceJudge | None = None) -> SearchResponse:
    profile = profile or active_profile(conn)
    response: SearchResponse
    for _ in range(2):
        candidates = retrieve(conn, root, request, profile, encoders=encoders)
        ordering = profile.joint
        exact = len(candidates) == 1 and candidates[0].signals.get("exact")
        if ordering is not None and not exact:
            if judge is None:
                from ken.retrieval.joint_model import load_judge
                judge = load_judge(ordering.model)
            matches = rank_candidates(request, candidates, judge=judge,
                rerank_limit=ordering.candidate_limit, rank_unit=ordering.rank_unit)
            if ordering.evidence_results:
                matches = refine_evidence(matches, root, request, judge=judge,
                    limit=ordering.evidence_results, max_windows=ordering.max_windows)
        else:
            matches = rank_candidates(request, candidates)
        response = present(matches, root, request, profile_version=profile.fingerprint)
        if not any(r["stale"] for r in response.results):
            return response
    return response
