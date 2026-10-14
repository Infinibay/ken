"""One explicit search path: retrieve, order entities, then expose current evidence."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ken.retrieval.candidates import active_profile, retrieve
from ken.retrieval.model import SearchRequest, SearchResponse
from ken.retrieval.presentation import present
from ken.retrieval.profile import Encoder, RetrievalProfile
from ken.retrieval.ranking import rank_candidates


def search(conn: sqlite3.Connection, root: Path, request: SearchRequest, *,
           profile: RetrievalProfile | None = None,
           encoders: Mapping[str, Encoder] | None = None) -> SearchResponse:
    profile = profile or active_profile(conn)
    response: SearchResponse
    for _ in range(2):
        candidates = retrieve(conn, root, request, profile, encoders=encoders)
        matches = rank_candidates(request, candidates)
        response = present(matches, root, request, profile_version=profile.fingerprint)
        if not any(r["stale"] for r in response.results):
            return response
    return response
