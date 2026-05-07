"""The three independent scoring channels.

Each function takes a sqlite3 connection (read-only is fine) and
returns a list of ``RankedItem``. Keys are file paths or symbol
qualnames; the merge step in ``ranker.merge`` reconciles them.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Iterable

import numpy as np

from ken.embedder import blob_to_vec
from ken.ranker import RankedItem

# ── Channel 1: Reactive ──────────────────────────────────────────────

LAMBDA = 0.15            # per-iteration decay rate (half-life ≈ 4.6 iters)
WINDOW_ITERATIONS = 30   # cap how far back we pull events from

# Per-event base weights. Mirrors infinidev / our own Rust port.
EVENT_WEIGHTS = {
    "retrieved": 0.5,
    "read": 1.0,
    "edit": 2.0,
    "edited": 2.0,        # alias used by some tools
    "cited": 2.5,
    "dismissed": -1.0,
    "neutral": 0.0,
    "write": 2.0,
}

# Pattern → multiplier (matches the Rust port we shipped earlier in
# this conversation; same constants infinidev uses).
PATTERN_MULTIPLIERS = {
    "cited": 2.5,
    "read_edit": 2.0,
    "edit_only": 1.5,
    "neutral": 1.0,
    "read_repeated": 0.7,
    "read_skipped": 0.3,
    "dismissed": 0.3,
}


def reactive_scores(conn: sqlite3.Connection, agent_id: str, current_iteration: int) -> list[RankedItem]:
    """Score files/symbols by what THIS session is touching.

    Decays old events exponentially; classifies the per-target event
    sequence into a productivity pattern; multiplies by the pattern.
    Drops final scores ≤ 0 (Dismissed clamps out, ReadSkipped barely
    dampens).
    """
    min_iter = max(0, current_iteration - WINDOW_ITERATIONS)
    rows = conn.execute(
        """
        SELECT i.event_type, i.target_path, i.iteration, i.weight
        FROM cr_interactions i
        JOIN cr_sessions s ON s.id = i.session_id
        WHERE s.agent_id = ? AND i.iteration >= ?
          AND i.target_kind = 'file' AND i.target_path IS NOT NULL
        """,
        (agent_id, min_iter),
    ).fetchall()

    raw: dict[str, float] = defaultdict(float)
    events: dict[str, list[str]] = defaultdict(list)
    edited_targets: set[str] = set()

    for row in rows:
        event_type = row["event_type"]
        path = row["target_path"]
        iteration = int(row["iteration"])
        caller_weight = float(row["weight"])
        base = EVENT_WEIGHTS.get(event_type, 0.0) * caller_weight
        decayed = base * math.exp(-LAMBDA * (current_iteration - iteration))
        raw[path] += decayed
        events[path].append(event_type)
        if event_type in {"edit", "edited"}:
            edited_targets.add(path)

    out: list[RankedItem] = []
    for path, raw_score in raw.items():
        pattern = _classify_pattern(events[path], edited_elsewhere=any(t != path for t in edited_targets))
        final = raw_score * PATTERN_MULTIPLIERS.get(pattern, 1.0)
        if final > 0.0:
            out.append(RankedItem(target=path, target_type="file", score=final, reason=f"reactive:{pattern}"))
    return out


def _classify_pattern(events: Iterable[str], *, edited_elsewhere: bool) -> str:
    """Same priorities as the Rust impl we shipped earlier."""
    has_cited = "cited" in events
    has_dismissed = "dismissed" in events
    has_read = "read" in events or "retrieved" in events
    has_edit = any(e in events for e in ("edit", "edited", "write"))
    read_count = sum(1 for e in events if e in ("read", "retrieved"))
    if has_cited:
        return "cited"
    if has_dismissed:
        return "dismissed"
    if has_read and has_edit:
        return "read_edit"
    if has_edit:
        return "edit_only"
    if read_count >= 3:
        return "read_repeated"
    if has_read and edited_elsewhere:
        return "read_skipped"
    return "neutral"


# ── Channel 2: Predictive ────────────────────────────────────────────

# How many past prompts we sweep for similarity. Past that, the cosine
# sweep is wasted work — distant matches don't carry useful signal.
PREDICTIVE_TOP_PROMPTS = 50
# Cosine threshold below which a past prompt is too dissimilar to count.
PREDICTIVE_MIN_SIM = 0.45
# Day-based decay: half-life of ~14 days. Old sessions get less weight.
PREDICTIVE_DECAY_DAYS = 14.0
PREDICTIVE_SCALE = 4.0


def predictive_scores(conn: sqlite3.Connection, prompt_embedding: np.ndarray) -> list[RankedItem]:
    """Score files by what past sessions with similar prompts edited / read.

    On a fresh install this is empty (no past prompts yet). It kicks
    in once the user has accumulated a few sessions.
    """
    rows = conn.execute(
        """
        SELECT id, session_id, embedding, created_at
        FROM cr_contexts
        WHERE kind = 'user_prompt' AND embedding IS NOT NULL
        ORDER BY created_at DESC LIMIT ?
        """,
        (PREDICTIVE_TOP_PROMPTS,),
    ).fetchall()
    if not rows:
        return []

    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)

    accum: dict[str, float] = defaultdict(float)
    now_ms = _now_ms(conn)

    for row in rows:
        v = blob_to_vec(row["embedding"])
        sim = float(np.dot(q, v / (np.linalg.norm(v) + 1e-12)))
        if sim < PREDICTIVE_MIN_SIM:
            continue
        days_ago = max(0.0, (now_ms - int(row["created_at"])) / (1000 * 60 * 60 * 24))
        decay = math.exp(-days_ago / PREDICTIVE_DECAY_DAYS)
        contribution = sim * sim * decay  # sim² rewards confident matches
        # Pull every target the past session interacted with, weighted by
        # the session's own pattern multiplier (read_edit etc.).
        score_rows = conn.execute(
            """
            SELECT target_path, score, pattern
            FROM cr_session_scores
            WHERE session_id = ? AND target_kind = 'file' AND target_path IS NOT NULL
            """,
            (int(row["session_id"]),),
        ).fetchall()
        for sr in score_rows:
            mult = PATTERN_MULTIPLIERS.get(sr["pattern"], 1.0)
            accum[sr["target_path"]] += contribution * float(sr["score"]) * mult

    out: list[RankedItem] = []
    for path, val in accum.items():
        score = val * PREDICTIVE_SCALE
        if score > 0:
            out.append(RankedItem(target=path, target_type="file", score=score, reason="predictive"))
    return out


def _now_ms(conn: sqlite3.Connection) -> int:
    # Single source of truth for "now"; keeps tests deterministic-ish.
    row = conn.execute("SELECT CAST(strftime('%s','now')*1000 AS INTEGER) AS ms").fetchone()
    return int(row["ms"])


# ── Channel 3: Fuzzy symbol / file ───────────────────────────────────

FUZZY_FILE_MIN_SIM = 0.40
FUZZY_FILE_SCALE = 4.5
FUZZY_SYMBOL_MIN_SIM = 0.45
FUZZY_SYMBOL_SCALE = 5.0
FUZZY_SYMBOL_BONUS = 0.5  # symbols slightly preferred over their file


def fuzzy_scores(
    conn: sqlite3.Connection, prompt_embedding: np.ndarray
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Cosine sweep of the prompt against every embedded symbol + file.

    Returns ``(file_items, symbol_items)``. Vectorised in numpy — for
    the project sizes we target (~10–100 K embeddings) this runs in
    single-digit milliseconds. We can swap to sqlite-vec / faiss later
    if it ever becomes the bottleneck (it won't).
    """
    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)

    file_items = _fuzzy_files(conn, q)
    symbol_items = _fuzzy_symbols(conn, q)
    return file_items, symbol_items


def _fuzzy_files(conn: sqlite3.Connection, q: np.ndarray) -> list[RankedItem]:
    rows = conn.execute(
        "SELECT path, embedding FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    paths = [r["path"] for r in rows]
    mat = np.asarray(
        [blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32
    )
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    out: list[RankedItem] = []
    for path, sim in zip(paths, sims):
        s = float(sim)
        if s < FUZZY_FILE_MIN_SIM:
            continue
        score = (s - FUZZY_FILE_MIN_SIM) * FUZZY_FILE_SCALE / (1.0 - FUZZY_FILE_MIN_SIM)
        out.append(RankedItem(target=path, target_type="file", score=score, reason=f"fuzzy:{s:.2f}"))
    return out


def _fuzzy_symbols(conn: sqlite3.Connection, q: np.ndarray) -> list[RankedItem]:
    rows = conn.execute(
        """
        SELECT s.qualname, s.name, s.embedding, f.path AS file_path, s.line_start
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE s.embedding IS NOT NULL
        """
    ).fetchall()
    if not rows:
        return []
    mat = np.asarray(
        [blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32
    )
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms

    out: list[RankedItem] = []
    for r, sim in zip(rows, sims):
        s = float(sim)
        if s < FUZZY_SYMBOL_MIN_SIM:
            continue
        # Score similarly to files but a bit tighter and bonused: a hit
        # at sim 0.6 lands at ~3 (vs the file's ~2.7).
        score = (s - FUZZY_SYMBOL_MIN_SIM) * FUZZY_SYMBOL_SCALE / (1.0 - FUZZY_SYMBOL_MIN_SIM) + FUZZY_SYMBOL_BONUS
        target = f"{r['qualname']} ({r['file_path']}:{r['line_start']})"
        out.append(RankedItem(target=target, target_type="symbol", score=score, reason=f"fuzzy:{s:.2f}"))
    return out
