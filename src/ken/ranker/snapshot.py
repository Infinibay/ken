"""Persist per-target productivity scores at session end.

The reactive channel computes "what's hot in this session" from
``cr_interactions`` on every prompt. At session-end we lift that
into ``cr_session_scores`` so future sessions can use it as
historical evidence for the predictive channel and the cooccurrence
boost.

Once written to ``cr_session_scores`` the row is read-only — even
re-running an old session can't rewrite history.
"""

from __future__ import annotations

import sqlite3
import time

from ken.ranker.channels import reactive_scores


def snapshot_session_scores(conn: sqlite3.Connection, agent_id: str, current_iteration: int) -> int:
    """Compute reactive scores and persist them as cr_session_scores.

    Returns the number of rows written. Idempotent at the row level —
    we DELETE existing rows for the session before inserting so a
    second snapshot replaces the first.
    """
    row = conn.execute(
        "SELECT id FROM cr_sessions WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if row is None:
        return 0
    session_pk = int(row["id"])

    items = reactive_scores(conn, agent_id, current_iteration)
    if not items:
        # Still drop any prior rows — a session that ended up empty
        # shouldn't leave stale scores behind.
        with conn:
            conn.execute("DELETE FROM cr_session_scores WHERE session_id = ?", (session_pk,))
        return 0

    now_ms = int(time.time() * 1000)
    with conn:
        conn.execute("DELETE FROM cr_session_scores WHERE session_id = ?", (session_pk,))
        conn.executemany(
            """
            INSERT INTO cr_session_scores
                (session_id, target_kind, target_id, target_path, score, pattern, created_at)
            VALUES (?, ?, NULL, ?, ?, ?, ?)
            """,
            [
                (
                    session_pk,
                    "file",
                    it.target,
                    it.score,
                    _pattern_from_reason(it.reason),
                    now_ms,
                )
                for it in items
            ],
        )
    return len(items)


def _pattern_from_reason(reason: str) -> str:
    """Extract the pattern label from a reactive reason string.

    Reasons follow ``"reactive:<pattern>"``; default to neutral if a
    caller passed something else.
    """
    if reason.startswith("reactive:"):
        return reason.split(":", 1)[1]
    return "neutral"
