"""stdio MCP server — entrypoint for ``ken mcp``.

We use the ``FastMCP`` decorator API from the official Python SDK; it
takes care of the JSON-RPC framing on stdin/stdout. Each tool is a
plain function with type annotations — the SDK derives the JSON
schema for ``tools/list`` automatically.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ken import _paths
from ken.db import connect
from ken.memory import recall, remember
from ken.search import search_files, search_symbols

logger = logging.getLogger("ken.mcp")

# Each `ken mcp` is a *single project* server — coding agents launch
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


# ---- FastMCP server tools ----------------------------------------------

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
    with _conn() as conn:
        return search_files(conn, query, limit=limit, project_root=_PROJECT_ROOT)


@mcp.tool()
def ken_search_symbols(query: str, limit: int = 10) -> list[dict]:
    """Search the project's indexed symbols (functions, classes, methods) for
    ones semantically relevant to *query*.

    Cosine similarity against per-symbol embeddings (built from
    ``"{kind} {name} — {docstring_first_line}"``). Returns the top
    *limit* hits with their location and one-line doc.
    """
    with _conn() as conn:
        return search_symbols(conn, query, limit=limit, project_root=_PROJECT_ROOT)


@mcp.tool()
def ken_remember(topic: str, content: str, tags: list[str] | None = None) -> dict:
    """Write a finding for future sessions to recall.

    *topic* is a short lookup key (unique — re-using a topic updates
    the existing row). *content* is the body — usually a few sentences
    capturing a fact you don't want to re-derive next time.
    """
    with _conn() as conn:
        return remember(conn, topic, content, tags=tags)


@mcp.tool()
def ken_recall(query: str, limit: int = 5) -> list[dict]:
    """Search previously-saved findings by semantic similarity to *query*."""
    with _conn() as conn:
        return recall(conn, query, limit=limit)


@mcp.tool()
def ken_rank(query: str = "", verbose: int = 1, max_chars: int = 0) -> dict:
    """Re-render the context-rank for the current session at a chosen verbosity.

    The default ``<context-rank>`` block injected before each user
    prompt is intentionally terse. Call this when you want more detail:

    * ``verbose=0`` — same compact list-only format as the auto-injected
      block.
    * ``verbose=1`` — top 5 files with a 3-line outline of each and a
      ranked symbols section.
    * ``verbose=2`` — top 8 files with a 12-line outline of each plus
      symbols. Largest payload.

    Set ``max_chars`` to a positive integer to cap the rendered block
    by dropping whole interior lines while preserving valid tags.

    With *query* empty (default), this re-renders the ranker's cached
    output for the most recent prompt — cheap, no recomputation. Pass
    a *query* to run the ranker against that intent without reactive
    session carry-over.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    resp = daemon_client.post(
        _PROJECT_ROOT,
        "/rank",
        {"query": query, "verbose": int(verbose), "max_chars": int(max_chars)},
    )
    if resp is None:
        return {"ok": False, "error": "daemon unreachable"}
    return resp


@mcp.tool()
def ken_explain_rank(query: str = "") -> dict:
    """Per-channel breakdown of the ranker for a query (or the last prompt).

    Returns each channel's raw output (traceback/explicit / reactive /
    predictive / fuzzy / lexical / findings), the merged pre-boost scores, the per-boost
    score deltas (symbol-file affinity, freshness, co-occurrence, test/import
    affinity, dismissal penalty), and the final
    ordering. Use this when "why didn't file X show up?" or "where did
    that score come from?" matters more than the rendered block.

    *query* defaults to the most recent prompt in the active session.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
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
    Requires a running daemon with an active hook-backed session.
    """
    from ken.daemon import client as daemon_client

    assert _PROJECT_ROOT is not None
    health = daemon_client.health(_PROJECT_ROOT)
    if not health or health.get("sessions_active", 0) == 0:
        return {
            "ok": False,
            "error": (
                "no active session — open a coding agent inside the project "
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
