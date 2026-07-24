"""Behavioural retrieval: prompt-intent -> files actually touched.

Distinct from ``ken_search_files`` (content-embedding match): this is
relevance-*by-outcome*. ken already embeds every ``user_prompt`` in
``cr_contexts`` and anchors interactions to it via ``context_id``. So:

  1. embed the incoming query,
  2. take the nearest historical prompts by cosine,
  3. tally the files those turns touched, weighted by prompt-similarity x
     interaction weight, deduped per session.

It returns the matched prompt texts and their similarities alongside the
files, so the agent sees *why* each file was routed and can self-discount a
thin match. Degrades gracefully: a fresh repo with no prompt log returns [].
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from ken.embedder import get_embedder, rank_against


def intent_history(
    conn,
    query: str,
    *,
    k_prompts: int = 12,
    limit: int = 15,
    project_root: Path | None = None,
) -> dict:
    """Return files historically touched for prompts similar to *query*."""
    rows = conn.execute(
        """
        SELECT id, session_id, content, embedding
        FROM cr_contexts
        WHERE kind = 'user_prompt' AND embedding IS NOT NULL
        """
    ).fetchall()
    if not rows:
        return {"ok": True, "query": query, "files": [],
                "note": "no embedded prompt history yet"}

    q = get_embedder().embed_query(query)
    sims, kept = rank_against(q, [r["embedding"] for r in rows], strict=False)
    rows = [rows[i] for i in kept]
    if not rows:
        return {"ok": True, "query": query, "files": [],
                "note": "stored prompt vectors predate the current embedding model"}

    order = np.argsort(-sims)[: max(1, int(k_prompts))]
    matched = [(rows[i], float(sims[i])) for i in order if sims[i] > 0.2]
    if not matched:
        return {"ok": True, "query": query, "files": [],
                "note": "no sufficiently similar prior prompts"}

    # Aggregate the interactions anchored to those prompt turns.
    file_score: dict[str, float] = defaultdict(float)
    file_hits: dict[str, int] = defaultdict(int)
    file_sessions: dict[str, set[int]] = defaultdict(set)
    for ctx, sim in matched:
        inter = conn.execute(
            """
            SELECT target_path, weight, session_id
            FROM cr_interactions
            WHERE context_id = ? AND target_path IS NOT NULL
            """,
            (int(ctx["id"]),),
        ).fetchall()
        seen_in_turn: set[str] = set()
        for it in inter:
            p = it["target_path"]
            if not p or p in seen_in_turn:
                continue
            seen_in_turn.add(p)
            file_score[p] += sim * float(it["weight"] or 1.0)
            file_hits[p] += 1
            file_sessions[p].add(int(it["session_id"]))

    if project_root is not None:
        root = project_root.resolve()
        for p in list(file_score):
            if not (root / p).exists():
                del file_score[p]

    ranked = sorted(file_score.items(), key=lambda kv: -kv[1])[: max(1, int(limit))]
    files = [
        {
            "path": p,
            "behavioral_score": round(score, 3),
            "times_touched": file_hits[p],
            "sessions": len(file_sessions[p]),
        }
        for p, score in ranked
    ]
    return {
        "ok": True,
        "query": query,
        "matched_prompts": [
            {"text": (ctx["content"] or "")[:160], "similarity": round(sim, 3)}
            for ctx, sim in matched[:5]
        ],
        "files": files,
    }
