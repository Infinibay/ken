"""One explicit search path: retrieve, order entities, then expose current evidence."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ken.retrieval.candidates import active_profile, retrieve, owner_descriptions
from ken.retrieval.model import SearchRequest, SearchResponse
from ken.retrieval.presentation import present
from ken.retrieval.evidence import refine_evidence
from ken.retrieval.profile import Encoder, RetrievalProfile
from ken.retrieval.ranking import RelevanceJudge, rank_candidates
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.source_evidence import refine_source_evidence


def search(conn: sqlite3.Connection, root: Path, request: SearchRequest, *,
           profile: RetrievalProfile | None = None,
           encoders: Mapping[str, Encoder] | None = None,
           judge: RelevanceJudge | None = None,
           owner_ranker: EvidenceReranker | None = None) -> SearchResponse:
    profile = profile or active_profile(conn)
    response: SearchResponse
    for _ in range(2):
        with retrieval_snapshot(conn):
            candidates = retrieve(conn, root, request, profile, encoders=encoders)
            ordering = profile.joint
            exact = len(candidates) == 1 and candidates[0].signals.get('exact')
            if profile.evidence is not None and not exact:
                if owner_ranker is None:
                    raise ValueError('evidence ranking profile requires its pinned owner ranker')
                owner_ranker.validate(profile.evidence)
                expanded = owner_ranker.prepare_query(request.query)
                matches = owner_ranker.rank(request, candidates, owner_descriptions(conn, candidates),
                                            expanded_query=expanded)
                matches = refine_source_evidence(matches, root, request, query=expanded,
                                                 stem_words=owner_ranker.stem_words)
            elif ordering is not None and not exact:
                if judge is None:
                    from ken.retrieval.joint_model import load_judge
                    judge = load_judge(ordering.model)
                matches = rank_candidates(request, candidates, judge=judge,
                    rerank_limit=ordering.candidate_limit, rank_unit=ordering.rank_unit)
                if ordering.evidence_results:
                    matches = refine_evidence(matches, root, request, judge=judge,
                        limit=ordering.evidence_results, max_windows=ordering.max_windows,
                        max_fragments=ordering.max_fragments)
            else:
                matches = rank_candidates(request, candidates)
        response = present(matches, root, request, profile_version=profile.fingerprint)
        if not any(r["stale"] for r in response.results):
            return response
    return response
