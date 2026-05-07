"""stdio MCP server — entrypoint for ``ken mcp``.

We use the ``FastMCP`` decorator API from the official Python SDK; it
takes care of the JSON-RPC framing on stdin/stdout. Each tool is a
plain function with type annotations — the SDK derives the JSON
schema for ``tools/list`` automatically.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from mcp.server.fastmcp import FastMCP

from ken import _paths
from ken.db import connect
from ken.embedder import blob_to_vec, get_embedder, vec_to_blob

logger = logging.getLogger("ken.mcp")

# Each `ken mcp` is a *single project* server — Claude Code launches
# one instance per workspace. The project root is resolved once at
# startup; if it's not a ken project we fail fast so the user sees
# a clear error in their MCP logs.
_PROJECT_ROOT: Path | None = None


def run(start: Path) -> int:
    """Resolve the project root, then hand control to FastMCP's run loop."""
    global _PROJECT_ROOT
    root = _paths.find_project_root(start.resolve()) or start.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"ken mcp: no .ken project at {root}", file=sys.stderr)
        return 1
    _PROJECT_ROOT = root
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("ken mcp ready project_root=%s", root)
    mcp.run()
    return 0


# ---- FastMCP server with the 5 tools -----------------------------------

mcp = FastMCP("ken")


def _conn() -> sqlite3.Connection:
    if _PROJECT_ROOT is None:
        raise RuntimeError("MCP server not initialised — call run() first")
    return connect(_paths.db_path(_PROJECT_ROOT))


@mcp.tool()
def ken_search_files(query: str, limit: int = 8) -> list[dict]:
    """Search the project's indexed files for ones semantically relevant to *query*.

    Cosine similarity against per-file embeddings (built from each
    file's language + base name + top symbol names — same shape the
    ranker's fuzzy channel uses). Returns the top *limit* hits with
    their score and a short symbol outline.
    """
    embedder = get_embedder()
    q = embedder.embed_query(query)
    q = q / (np.linalg.norm(q) + 1e-12)

    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, path, language, embedding FROM ci_files WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return []
        mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1) + 1e-12
        sims = (mat @ q) / norms

        ranked: list[tuple[float, sqlite3.Row]] = sorted(
            zip(sims.tolist(), rows), key=lambda x: x[0], reverse=True
        )[: max(1, limit)]

        out: list[dict] = []
        for score, row in ranked:
            outline_rows = conn.execute(
                "SELECT kind, name, line_start FROM ci_symbols "
                "WHERE file_id = ? ORDER BY line_start LIMIT 8",
                (int(row["id"]),),
            ).fetchall()
            out.append(
                {
                    "path": row["path"],
                    "language": row["language"] or "text",
                    "score": round(float(score), 3),
                    "symbols": [
                        {"kind": r["kind"], "name": r["name"], "line": int(r["line_start"])}
                        for r in outline_rows
                    ],
                }
            )
    return out


@mcp.tool()
def ken_search_symbols(query: str, limit: int = 10) -> list[dict]:
    """Search the project's indexed symbols (functions, classes, methods) for
    ones semantically relevant to *query*.

    Cosine similarity against per-symbol embeddings (built from
    ``"{kind} {name} — {docstring_first_line}"``). Returns the top
    *limit* hits with their location and one-line doc.
    """
    embedder = get_embedder()
    q = embedder.embed_query(query)
    q = q / (np.linalg.norm(q) + 1e-12)

    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.kind, s.name, s.qualname, s.line_start, s.line_end,
                   s.docstring, s.embedding, f.path AS file_path
            FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
            WHERE s.embedding IS NOT NULL
            """
        ).fetchall()
    if not rows:
        return []
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    ranked = sorted(zip(sims.tolist(), rows), key=lambda x: x[0], reverse=True)[: max(1, limit)]
    return [
        {
            "qualname": r["qualname"],
            "kind": r["kind"],
            "file": r["file_path"],
            "line": int(r["line_start"]),
            "line_end": int(r["line_end"]),
            "docstring": r["docstring"],
            "score": round(float(score), 3),
        }
        for score, r in ranked
    ]


@mcp.tool()
def ken_remember(topic: str, content: str, tags: list[str] | None = None) -> dict:
    """Write a finding for future sessions to recall.

    *topic* is a short lookup key (unique — re-using a topic updates
    the existing row). *content* is the body — usually a few sentences
    capturing a fact you don't want to re-derive next time.
    """
    if not topic.strip() or not content.strip():
        return {"ok": False, "error": "topic and content must be non-empty"}
    tags_json = json.dumps([t for t in (tags or []) if isinstance(t, str)])
    embed_text = f"{topic.strip()}\n\n{content.strip()[:1024]}"
    try:
        emb = vec_to_blob(get_embedder().embed_query(embed_text))
    except Exception:  # pragma: no cover
        emb = None
    now_ms = int(time.time() * 1000)
    with _conn() as conn:
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
            (topic.strip(), content.strip(), tags_json, emb, now_ms, now_ms),
        )
    return {"ok": True, "topic": topic.strip()}


@mcp.tool()
def ken_recall(query: str, limit: int = 5) -> list[dict]:
    """Search previously-saved findings by semantic similarity to *query*."""
    embedder = get_embedder()
    q = embedder.embed_query(query)
    q = q / (np.linalg.norm(q) + 1e-12)
    with _conn() as conn:
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


@mcp.tool()
def ken_rank(query: str = "", verbose: int = 1) -> dict:
    """Re-render the context-rank for the current session at a chosen verbosity.

    The default ``<context-rank>`` block injected before each user
    prompt is intentionally terse. Call this when you want more detail:

    * ``verbose=0`` — same one-line-per-file format as the auto-injected
      block (useful if you missed it).
    * ``verbose=1`` — top 5 files with a 3-line outline of each and a
      ranked symbols section.
    * ``verbose=2`` — top 8 files with a 12-line outline of each plus
      symbols. Largest payload.

    With *query* empty (default), this re-renders the ranker's cached
    output for the most recent prompt — cheap, no recomputation. Pass
    a *query* to run the ranker against a different intent (still using
    your current session's reactive context).
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    health = daemon_client.health(_PROJECT_ROOT)
    if not health or health.get("sessions_active", 0) == 0:
        return {
            "ok": False,
            "error": (
                "no active claude session — open claude inside the project "
                "and try again"
            ),
        }
    resp = daemon_client.post(
        _PROJECT_ROOT,
        "/rank",
        {"query": query, "verbose": int(verbose)},
    )
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp


@mcp.tool()
def ken_explain_rank(query: str = "") -> dict:
    """Per-channel breakdown of the ranker for a query (or the last prompt).

    Returns each channel's raw output (explicit / reactive / predictive
    / fuzzy), the merged pre-boost scores, the per-boost score deltas
    (freshness, co-occurrence, dismissal penalty), and the final
    ordering. Use this when "why didn't file X show up?" or "where did
    that score come from?" matters more than the rendered block.

    *query* defaults to the most recent prompt in the active session.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    health = daemon_client.health(_PROJECT_ROOT)
    if not health or health.get("sessions_active", 0) == 0:
        return {"ok": False, "error": "no active claude session"}
    resp = daemon_client.post(_PROJECT_ROOT, "/explain", {"query": query})
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp


@mcp.tool()
def ken_dismiss(target: str, reason: str = "") -> dict:
    """Explicit "this file wasn't what I was looking for" signal.

    Records a ``dismissed`` interaction against the current active
    session — the predictive ranker will treat this target as a
    negative example for similar prompts in future sessions.
    Requires a running daemon (i.e. an active claude session).
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    health = daemon_client.health(_PROJECT_ROOT)
    if not health or health.get("sessions_active", 0) == 0:
        return {
            "ok": False,
            "error": (
                "no active claude session — open claude inside the project "
                "and try again"
            ),
        }
    resp = daemon_client.post(
        _PROJECT_ROOT,
        "/interactions/dismiss",
        {"target": target, "reason": reason},
    )
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp
