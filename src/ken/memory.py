"""Persistent findings for future coding sessions."""

from __future__ import annotations

import json
import sqlite3
import time

import numpy as np

from ken.embedder import blob_to_vec, get_embedder, vec_to_blob


def remember(
    conn: sqlite3.Connection, topic: str, content: str, tags: list[str] | None = None
) -> dict:
    """Store or update a reusable finding."""
    topic = topic.strip()
    content = content.strip()
    if not topic or not content:
        return {"ok": False, "error": "topic and content must be non-empty"}
    tags_json = json.dumps([t for t in (tags or []) if isinstance(t, str)])
    embed_text = f"{topic}\n\n{content[:1024]}"
    try:
        emb = vec_to_blob(get_embedder().embed_query(embed_text))
    except Exception:  # pragma: no cover
        emb = None
    now_ms = int(time.time() * 1000)
    conn.execute(
        """
        INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic) DO UPDATE SET
            content = excluded.content,
            tags = excluded.tags,
            embedding = excluded.embedding,
            updated_at = excluded.updated_at
        """,
        (topic, content, tags_json, emb, now_ms, now_ms),
    )
    return {"ok": True, "topic": topic}


def recall(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Search saved findings by embedding cosine similarity."""
    q = get_embedder().embed_query(query)
    q = q / (np.linalg.norm(q) + 1e-12)
    rows = conn.execute(
        "SELECT topic, content, tags, embedding, updated_at "
        "FROM cr_findings WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    ranked = sorted(zip(sims.tolist(), rows), key=lambda x: x[0], reverse=True)[: max(1, limit)]
    return [
        {
            "topic": r["topic"],
            "content": r["content"],
            "tags": json.loads(r["tags"] or "[]"),
            "score": round(float(score), 3),
        }
        for score, r in ranked
    ]


def format_recall_hits(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        tags = hit.get("tags") or []
        suffix = f" [{' '.join(tags)}]" if tags else ""
        lines.append(f"{hit['score']:.3f}  {hit['topic']}{suffix}")
        lines.append(f"       {hit['content']}")
    return "\n".join(lines)
