"""Persist the strongest productive turn for every file in a session.

Uses the existing raw-score + pattern format: old databases need no migration
or rebuild, and older readers can consume new snapshots. Reactive recency is
only for live ranking; it must not erase early work from durable memory.
"""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict

from ken.ranker.channels import PATTERN_MULTIPLIERS, historical_file_scores


def snapshot_session_scores(conn: sqlite3.Connection, agent_id: str, current_iteration: int) -> int:
    """Atomically replace a session snapshot, retaining work from every turn.

    NULL anchors in legacy history form one group. Multiple turns touching the
    same file contribute their strongest observation, rather than inflating it
    with session length. current_iteration is retained for caller compatibility.
    Callers sharing a connection across threads must hold their connection lock.
    """
    row = conn.execute(
        "SELECT id FROM cr_sessions WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
        (agent_id,),
    ).fetchone()
    if row is None:
        return 0
    session_pk = int(row["id"])
    turns: dict[int | None, list[sqlite3.Row]] = defaultdict(list)
    for event in conn.execute(
        "SELECT context_id, target_path, event_type, weight FROM cr_interactions "
        "WHERE session_id = ? AND target_kind = 'file' AND target_path IS NOT NULL",
        (session_pk,),
    ):
        turns[event["context_id"]].append(event)
    best: dict[str, tuple[float, str]] = {}
    for events in turns.values():
        for path, (raw, pattern) in historical_file_scores(events).items():
            prev_raw, prev_pattern = best.get(path, (0.0, "neutral"))
            if raw * PATTERN_MULTIPLIERS[pattern] > prev_raw * PATTERN_MULTIPLIERS[prev_pattern]:
                best[path] = (raw, pattern)

    now_ms = int(time.time() * 1000)
    # SAVEPOINT works with both autocommit daemon connections and callers
    # already inside a transaction. with conn alone is not atomic in autocommit.
    conn.execute("SAVEPOINT ken_session_snapshot")
    try:
        conn.execute("DELETE FROM cr_session_scores WHERE session_id = ?", (session_pk,))
        conn.executemany(
            "INSERT INTO cr_session_scores "
            "(session_id, target_kind, target_id, target_path, score, pattern, created_at) "
            "VALUES (?, 'file', NULL, ?, ?, ?, ?)",
            [(session_pk, path, raw, pattern, now_ms) for path, (raw, pattern) in best.items()],
        )
    except BaseException:
        conn.execute("ROLLBACK TO ken_session_snapshot")
        raise
    finally:
        conn.execute("RELEASE ken_session_snapshot")
    return len(best)
