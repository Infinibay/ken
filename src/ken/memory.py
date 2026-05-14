"""Persistent findings for future coding sessions."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

import numpy as np

from ken.embedder import blob_to_vec, get_embedder, vec_to_blob

DEFAULT_RECALL_MIN_SCORE = 0.25
FINDING_KINDS = {"finding", "persistent_rule", "experimental_finding", "hypothesis"}


def remember(
    conn: sqlite3.Connection,
    topic: str,
    content: str,
    tags: list[str] | None = None,
    kind: str | None = None,
) -> dict:
    """Store or update a reusable finding."""
    topic = topic.strip()
    content = content.strip()
    if not topic or not content:
        return {"ok": False, "error": "topic and content must be non-empty"}
    clean_tags = [t for t in (tags or []) if isinstance(t, str)]
    if kind is not None:
        kind = kind.strip()
        if kind not in FINDING_KINDS:
            return {
                "ok": False,
                "error": f"kind must be one of: {', '.join(sorted(FINDING_KINDS))}",
            }
        clean_tags = [t for t in clean_tags if not t.startswith(("kind:", "type:"))]
        clean_tags.append(f"kind:{kind}")
    tags_json = json.dumps(clean_tags)
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


def forget(conn: sqlite3.Connection, topic: str) -> dict:
    """Delete a saved finding by exact topic."""
    topic = topic.strip()
    if not topic:
        return {"ok": False, "error": "topic must be non-empty"}
    cur = conn.execute("DELETE FROM cr_findings WHERE topic = ?", (topic,))
    deleted = int(cur.rowcount if cur.rowcount is not None else 0)
    return {"ok": deleted > 0, "topic": topic, "deleted": deleted}


def list_findings(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    tag: str | None = None,
) -> list[dict]:
    """Return recent findings, optionally filtered by tag."""
    rows = conn.execute(
        """
        SELECT topic, content, tags, created_at, updated_at
        FROM cr_findings
        ORDER BY updated_at DESC, topic
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()
    out: list[dict] = []
    wanted = tag.strip() if isinstance(tag, str) and tag.strip() else None
    for r in rows:
        tags = json.loads(r["tags"] or "[]")
        if wanted is not None and wanted not in tags:
            continue
        out.append(_finding_row_to_dict(r, tags=tags))
    return out


def recall(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 5,
    *,
    min_score: float | None = DEFAULT_RECALL_MIN_SCORE,
) -> list[dict]:
    """Search saved findings by embedding cosine similarity."""
    q = get_embedder().embed_query(query)
    q = q / (np.linalg.norm(q) + 1e-12)
    rows = conn.execute(
        "SELECT topic, content, tags, embedding, created_at, updated_at "
        "FROM cr_findings WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    min_score = 0.0 if min_score is None else max(0.0, float(min_score))
    ranked = [
        (score, row)
        for score, row in sorted(zip(sims.tolist(), rows), key=lambda x: x[0], reverse=True)
        if float(score) >= min_score
    ][: max(1, limit)]
    return [
        {
            **_finding_row_to_dict(r),
            "score": round(float(score), 3),
            "score_kind": "cosine_similarity",
            "min_score": min_score,
        }
        for score, r in ranked
    ]


def format_recall_hits(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        tags = hit.get("tags") or []
        suffix = f" [{' '.join(tags)}]" if tags else ""
        meta = []
        if hit.get("type"):
            meta.append(str(hit["type"]))
        if hit.get("updated_at"):
            meta.append(f"updated {hit['updated_at']}")
        meta_text = f" ({'; '.join(meta)})" if meta else ""
        lines.append(f"{hit['score']:.3f}  {hit['topic']}{suffix}{meta_text}")
        lines.append(f"       {hit['content']}")
    return "\n".join(lines)


def _finding_row_to_dict(
    row: sqlite3.Row,
    *,
    tags: list[str] | None = None,
) -> dict:
    parsed_tags = json.loads(row["tags"] or "[]") if tags is None else tags
    kind, type_source = _finding_kind(parsed_tags)
    return {
        "topic": row["topic"],
        "content": row["content"],
        "tags": parsed_tags,
        "type": kind,
        "type_source": type_source,
        "created_at": _ms_to_iso(int(row["created_at"])),
        "updated_at": _ms_to_iso(int(row["updated_at"])),
    }


def _ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _finding_kind(tags: list[str]) -> tuple[str, str]:
    normalized = [tag.strip().lower() for tag in tags if isinstance(tag, str)]
    for prefix in ("kind:", "type:"):
        for tag in normalized:
            if tag.startswith(prefix):
                kind = tag.split(":", 1)[1]
                if kind in FINDING_KINDS:
                    return kind, "explicit"

    legacy = set(normalized)
    if "ken-rule" in legacy:
        return "persistent_rule", "legacy_tag"
    if {"negative-result", "bugfix"} & legacy:
        return "experimental_finding", "legacy_tag"
    if {"hypothesis", "research"} & legacy:
        return "hypothesis", "legacy_tag"
    return "finding", "default"
