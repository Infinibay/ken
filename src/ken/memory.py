"""Persistent findings for future coding sessions."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

from ken.embedder import cosine_against, get_embedder, stack_embeddings, vec_to_blob

DEFAULT_RECALL_MIN_SCORE = 0.25
FINDING_KINDS = {"finding", "persistent_rule", "experimental_finding", "hypothesis"}


def remember(
    conn: sqlite3.Connection,
    topic: str,
    content: str,
    tags: list[str] | None = None,
    kind: str | None = None,
    anchors: dict[str, str] | None = None,
) -> dict:
    """Store or update a reusable finding.

    *anchors* declares what the memory is about — ``{"file": "src/a.py"}``,
    ``{"tool": "pytest"}``, and so on (see ``findings_graph.ANCHOR_KINDS``).
    An anchored finding can be looked up by the thing that provoked it
    instead of by a query, which is what lets a caller surface it at the
    moment it becomes relevant rather than hoping someone searches for it.
    """
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
        # A stored finding is a *document*; ``recall`` supplies the query side.
        # Asymmetric models (e5, Qwen3) encode the two differently, so using
        # embed_query here would file every finding in the query space and
        # then search it with another query vector.
        emb = vec_to_blob(get_embedder().embed_passages([embed_text])[0])
    except Exception:  # pragma: no cover
        emb = None
    now_ms = int(time.time() * 1000)

    from ken.findings_graph import apply_remember, ensure_finding_graph, graph_enabled

    # Ensure tables + any pending backfill BEFORE opening the write txn, so
    # ensure's own BEGIN can't nest inside ours. Best-effort: a graph failure
    # here must never cost the user their finding.
    enabled = False
    try:
        ensure_finding_graph(conn)
        enabled = graph_enabled(conn)
    except Exception:  # pragma: no cover - defensive
        enabled = False
    try:
        conn.execute("BEGIN IMMEDIATE")
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
        # last_insert_rowid() is wrong on the DO UPDATE path — look the id up.
        row = conn.execute("SELECT id FROM cr_findings WHERE topic = ?", (topic,)).fetchone()
        if enabled:
            apply_remember(conn, int(row["id"]), f"{topic}\n{content}")
        if anchors:
            # After apply_remember: recompute_finding_refs spares anchors, but
            # writing them second keeps the order independent of that promise.
            # Isolated because the refs table belongs to the graph subsystem,
            # and the rule there is that a graph failure never costs the user
            # their finding — losing an anchor is recoverable, losing the
            # content is not.
            try:
                from ken.findings_graph import set_finding_anchors

                stored_anchors = set_finding_anchors(
                    conn, int(row["id"]), anchors, now_ms,
                )
            except Exception:  # pragma: no cover - defensive
                stored_anchors = 0
        conn.execute("COMMIT")
    except Exception as exc:  # pragma: no cover - defensive
        _safe_rollback(conn)
        return {"ok": False, "error": f"remember failed: {exc}"}
    out = {"ok": True, "topic": topic}
    if anchors:
        out["anchors"] = stored_anchors
    return out


def recall_by_anchor(
    conn: sqlite3.Connection,
    anchors: dict[str, str],
    *,
    limit: int = 3,
) -> list[dict]:
    """Findings anchored to any of *anchors*.

    The lookup a caller runs when something just happened — a file was
    opened, a command ran, an error came back — rather than when someone
    thought to search. Never raises: an unbuilt graph returns nothing.
    """
    from ken.findings_graph import ensure_finding_graph, find_by_anchor

    try:
        ensure_finding_graph(conn)
    except Exception:  # pragma: no cover - defensive
        return []
    return find_by_anchor(conn, anchors, limit=limit)


def forget(conn: sqlite3.Connection, topic: str) -> dict:
    """Delete a saved finding by exact topic.

    The FK cascade removes the finding's graph refs + edges; we then recompute
    the remaining edges so IDF-weighted couplings stay consistent.
    """
    topic = topic.strip()
    if not topic:
        return {"ok": False, "error": "topic must be non-empty"}

    from ken.findings_graph import apply_forget, ensure_finding_graph, graph_enabled

    enabled = False
    try:
        ensure_finding_graph(conn)
        enabled = graph_enabled(conn)
    except Exception:  # pragma: no cover - defensive
        enabled = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("DELETE FROM cr_findings WHERE topic = ?", (topic,))
        deleted = int(cur.rowcount if cur.rowcount is not None else 0)
        if enabled and deleted:
            apply_forget(conn)
        conn.execute("COMMIT")
    except Exception as exc:  # pragma: no cover - defensive
        _safe_rollback(conn)
        return {"ok": False, "error": f"forget failed: {exc}"}
    return {"ok": deleted > 0, "topic": topic, "deleted": deleted}


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:  # pragma: no cover - nothing to roll back
        pass


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
    rows = conn.execute(
        "SELECT topic, content, tags, embedding, created_at, updated_at "
        "FROM cr_findings WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    # Findings written by an earlier model are skipped rather than compared
    # across vector spaces; an entirely stale table raises with the fix named.
    mat, kept = stack_embeddings([r["embedding"] for r in rows], dim=int(q.shape[0]))
    if not kept:
        return []
    sims = cosine_against(q, mat)
    min_score = 0.0 if min_score is None else max(0.0, float(min_score))
    ranked = [
        (score, row)
        for score, row in sorted(
            ((float(s), rows[i]) for s, i in zip(sims.tolist(), kept)),
            key=lambda x: x[0],
            reverse=True,
        )
        if score >= min_score
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
