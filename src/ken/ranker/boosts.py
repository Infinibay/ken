"""Post-processing boosts. Modify scored items, never create new ones."""

from __future__ import annotations

import sqlite3
import time

import numpy as np

from ken.embedder import blob_to_vec
from ken.ranker import RankedItem

# ── Freshness ────────────────────────────────────────────────────────

FRESH_MAX_MULT = 1.3
FRESH_DECAY_DAYS = 7.0


def apply_freshness(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Multiplicative bump for files modified recently on disk.

    Linear decay from FRESH_MAX_MULT today to 1.0 at FRESH_DECAY_DAYS
    ago. Multiplicative *on top of* an existing score — this can't
    rescue an unranked file, only amplify one that already won.
    """
    if not files:
        return
    paths = [it.target for it in files]
    rows = conn.execute(
        f"SELECT path, mtime FROM ci_files WHERE path IN ({','.join('?' * len(paths))})",
        paths,
    ).fetchall()
    mtime_by_path: dict[str, int] = {r["path"]: int(r["mtime"]) for r in rows}
    now_ns = int(time.time() * 1e9)
    secs_per_day = 86_400
    for it in files:
        mtime_ns = mtime_by_path.get(it.target)
        if mtime_ns is None:
            continue
        days_ago = max(0.0, (now_ns - mtime_ns) / 1e9 / secs_per_day)
        if days_ago >= FRESH_DECAY_DAYS:
            continue
        mult = 1.0 + (FRESH_MAX_MULT - 1.0) * (1.0 - days_ago / FRESH_DECAY_DAYS)
        it.score *= mult
        it.reason = _append_reason(it.reason, f"fresh×{mult:.2f}")


# ── Co-occurrence ────────────────────────────────────────────────────

COOC_ANCHOR_MIN_SCORE = 0.6
COOC_MAX_ANCHORS = 5
COOC_MIN_SESSIONS = 2
COOC_PROPAGATION = 0.4
COOC_SATURATE_SESSIONS = 5
COOC_MIN_PROPAGATED = 0.3
COOC_LOOKBACK_DAYS = 90


def apply_cooc(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Boost files frequently accessed alongside the top anchors.

    For each anchor (file already scoring high), find other files that
    co-occurred in past sessions where the anchor was also useful.
    Saturating contribution by session count, with minimum 2 sessions
    of co-occurrence to count as signal.
    """
    if not files:
        return
    anchors = [it for it in files if it.score >= COOC_ANCHOR_MIN_SCORE][:COOC_MAX_ANCHORS]
    if not anchors:
        return
    anchor_paths = tuple(a.target for a in anchors)
    cutoff_ms = (int(time.time()) - COOC_LOOKBACK_DAYS * 86_400) * 1000

    # Sessions where one of the anchors was useful.
    placeholders = ",".join("?" * len(anchor_paths))
    rows = conn.execute(
        f"""
        SELECT DISTINCT session_id FROM cr_session_scores
        WHERE target_path IN ({placeholders})
          AND score >= ?
          AND created_at >= ?
        """,
        (*anchor_paths, COOC_ANCHOR_MIN_SCORE, cutoff_ms),
    ).fetchall()
    if not rows:
        return
    session_ids = tuple(int(r["session_id"]) for r in rows)
    sess_ph = ",".join("?" * len(session_ids))

    rows = conn.execute(
        f"""
        SELECT target_path, COUNT(DISTINCT session_id) AS sess, AVG(score) AS avg_score
        FROM cr_session_scores
        WHERE session_id IN ({sess_ph})
          AND target_path IS NOT NULL
          AND target_path NOT IN ({placeholders})
        GROUP BY target_path
        HAVING sess >= ?
        """,
        (*session_ids, *anchor_paths, COOC_MIN_SESSIONS),
    ).fetchall()

    by_path = {it.target: it for it in files}
    anchor_score_by_path = {a.target: a.score for a in anchors}
    avg_anchor = sum(anchor_score_by_path.values()) / len(anchors)
    for r in rows:
        path = r["target_path"]
        sess_count = int(r["sess"])
        contribution = (
            avg_anchor
            * COOC_PROPAGATION
            * min(sess_count / COOC_SATURATE_SESSIONS, 1.0)
        )
        if contribution < COOC_MIN_PROPAGATED:
            continue
        if path in by_path:
            by_path[path].score += contribution
            by_path[path].reason = _append_reason(by_path[path].reason, f"cooc+{contribution:.1f}")
        else:
            files.append(
                RankedItem(
                    target=path,
                    target_type="file",
                    score=contribution,
                    reason=f"cooc({sess_count}sess)",
                )
            )


# ── Dismissal penalty ────────────────────────────────────────────────
#
# When the user explicitly dismissed a file via `ken_dismiss` in a past
# session whose prompt was semantically close to the current one, knock
# its score down. Floors at zero — never negative, since merge already
# decided this file is in the running.
#
# We look at cr_interactions directly (rather than cr_session_scores)
# because a dismissed file's reactive score is filtered out at score≤0,
# so the snapshot pipeline drops it. The raw event survives in
# cr_interactions for exactly this reason.

DISMISS_SIM_THRESHOLD = 0.45
DISMISS_PENALTY = 1.5
DISMISS_LOOKBACK_PROMPTS = 50


def apply_dismissal_penalty(
    conn: sqlite3.Connection, prompt_embedding: np.ndarray, files: list[RankedItem]
) -> None:
    if not files:
        return
    rows = conn.execute(
        """
        SELECT id, session_id, embedding FROM cr_contexts
        WHERE kind = 'user_prompt' AND embedding IS NOT NULL
        ORDER BY created_at DESC LIMIT ?
        """,
        (DISMISS_LOOKBACK_PROMPTS,),
    ).fetchall()
    if not rows:
        return
    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)

    similar_session_ids: set[int] = set()
    for r in rows:
        v = blob_to_vec(r["embedding"])
        sim = float(np.dot(q, v / (np.linalg.norm(v) + 1e-12)))
        if sim >= DISMISS_SIM_THRESHOLD:
            similar_session_ids.add(int(r["session_id"]))
    if not similar_session_ids:
        return

    paths = [it.target for it in files]
    path_ph = ",".join("?" * len(paths))
    sess_ph = ",".join("?" * len(similar_session_ids))
    rows = conn.execute(
        f"""
        SELECT target_path, COUNT(DISTINCT session_id) AS n
        FROM cr_interactions
        WHERE event_type = 'dismissed'
          AND target_kind = 'file'
          AND target_path IN ({path_ph})
          AND session_id IN ({sess_ph})
        GROUP BY target_path
        """,
        (*paths, *similar_session_ids),
    ).fetchall()
    by_path = {it.target: it for it in files}
    for r in rows:
        n = int(r["n"])
        # Saturate the penalty at 3 dismissals — past that the user has
        # made themselves clear and we shouldn't compound the signal.
        damp = DISMISS_PENALTY * min(n, 3) / 3.0
        item = by_path[r["target_path"]]
        item.score = max(0.0, item.score - damp)
        item.reason = _append_reason(item.reason, f"-dismiss({damp:.1f})")


# ── Helpers ──────────────────────────────────────────────────────────


def _append_reason(existing: str, more: str) -> str:
    if not existing:
        return more
    return f"{existing} + {more}"
