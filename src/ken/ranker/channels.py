"""The three independent scoring channels.

Each function takes a sqlite3 connection (read-only is fine) and
returns a list of ``RankedItem``. Keys are file paths or symbol
qualnames; the merge step in ``ranker.merge`` reconciles them.
"""

from __future__ import annotations

import math
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable

import numpy as np

from ken.embedder import blob_to_vec
from ken.ranker import RankedItem

# ── Channel 1: Reactive ──────────────────────────────────────────────

LAMBDA = 0.15            # per-iteration decay rate (half-life ≈ 4.6 iters)
WINDOW_ITERATIONS = 30   # cap how far back we pull events from

# Per-turn decay applied on top of per-iteration decay. Each turn = one
# user→assistant ping-pong. Tool calls anchored to the just-finished
# turn (distance 1) keep full weight; one turn earlier gets 0.5×, two
# turns earlier 0.25×, etc. Aggressive on purpose — captures the
# user's directive to make recent prompts dominate older ones, even
# when older turns produced more raw events.
TURN_DECAY = 0.5

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

    Two stacked decays:

    * **Per iteration**: ``exp(-λ·Δi)`` — events older than ~5 iterations
      lose half their weight. Catches fine-grained "this just happened"
      vs "this happened a few tool calls ago".
    * **Per turn** (= ping-pong with the user): tool calls anchored to
      the just-finished turn keep full weight; each prior turn applies
      another ``TURN_DECAY`` factor. Reflects that the user's intent
      shifts with each new prompt.

    Productivity pattern then multiplies (Dismissed → 0.3×,
    ReadSkipped → 0.3× when session edited elsewhere, ReadEdit → 2.0×,
    etc.). Final scores ≤ 0 are dropped.
    """
    session_row = conn.execute(
        "SELECT id FROM cr_sessions WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if session_row is None:
        return []
    session_pk = int(session_row["id"])

    # Build the turn map: ordered user_prompt context_ids in this session,
    # 1-indexed by chronological order. The most recent prompt is the one
    # we just inserted via record_context — its rank == len(rank_map).
    prompt_rows = conn.execute(
        "SELECT id FROM cr_contexts WHERE session_id = ? AND kind = 'user_prompt' ORDER BY id",
        (session_pk,),
    ).fetchall()
    turn_rank: dict[int, int] = {int(r["id"]): i for i, r in enumerate(prompt_rows, start=1)}
    latest_turn = len(prompt_rows)

    min_iter = max(0, current_iteration - WINDOW_ITERATIONS)
    rows = conn.execute(
        """
        SELECT i.event_type, i.target_path, i.iteration, i.weight, i.context_id
        FROM cr_interactions i
        WHERE i.session_id = ? AND i.iteration >= ?
          AND i.target_kind = 'file' AND i.target_path IS NOT NULL
        """,
        (session_pk, min_iter),
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
        iter_decay = math.exp(-LAMBDA * (current_iteration - iteration))
        turn_mult = _turn_multiplier(row["context_id"], turn_rank, latest_turn)
        raw[path] += base * iter_decay * turn_mult
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


def _turn_multiplier(context_id: int | None, turn_rank: dict[int, int], latest_turn: int) -> float:
    """Per-turn decay factor for an interaction.

    * NULL context_id (event with no anchor — happens before the first
      prompt or in legacy data) → no per-turn adjustment (1.0).
    * Anchor unknown to the turn map → also 1.0; treated as
      "neutral" rather than penalising what we can't classify.
    * Otherwise: distance = ``latest_turn - anchor_turn`` ≥ 0.
      ``distance == 0`` means the event was attached to the prompt
      we're ranking *for* (rare, only if /prompts and a tool call
      raced) — treat as the just-finished turn (distance 1).
    """
    if context_id is None:
        return 1.0
    anchor_turn = turn_rank.get(int(context_id))
    if anchor_turn is None:
        return 1.0
    distance = max(1, latest_turn - anchor_turn)
    return TURN_DECAY ** (distance - 1)


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


# ── Explicit mentions ────────────────────────────────────────────────
#
# Targeted prompts ("fix the bug in src/auth.py", "what does Session.expire
# do?") shouldn't depend on fuzzy embedding luck — if the user named a
# real file or symbol, surface it directly. These items go through the
# same merge as the channels above, so they compete cleanly with reactive
# / predictive / fuzzy hits on the same target.

_PATH_RE = re.compile(r"\b[\w./\-]+\.[a-zA-Z]{1,5}\b(?::\d+(?:-\d+)?)?")
# Either backtick-quoted (group 1) or a CamelCase / Class.method
# identifier in plain prose (group 2). Lowercase identifiers without
# backticks are too noisy ("the function" → "the").
_IDENT_RE = re.compile(r"`([^`\n]+)`|\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\b")

_KNOWN_EXTS = frozenset(
    "py pyi rs js jsx mjs cjs ts tsx go java md rst json yaml yml toml sh sql html css".split()
)

EXPLICIT_FILE_SCORE = 5.0
EXPLICIT_SYMBOL_SCORE = 5.5
EXPLICIT_FILE_FROM_SYMBOL = 3.5  # symbol named → boost its file too, but less


def explicit_mentions(
    conn: sqlite3.Connection, prompt: str
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Lift any indexed file / symbol the user named in their prompt.

    Returns ``(file_items, symbol_items)``. Empty when nothing matches.
    """
    if not prompt:
        return [], []

    file_items: list[RankedItem] = []
    symbol_items: list[RankedItem] = []
    seen_files: set[str] = set()
    seen_symbols: set[str] = set()

    for m in _PATH_RE.findall(prompt):
        base = m.split(":")[0]
        ext = base.rsplit(".", 1)[-1].lower()
        if ext not in _KNOWN_EXTS:
            continue
        if base in seen_files:
            continue
        seen_files.add(base)
        rows = conn.execute(
            "SELECT path FROM ci_files WHERE path = ? OR path LIKE ?",
            (base, f"%/{base}"),
        ).fetchall()
        for r in rows:
            file_items.append(
                RankedItem(
                    target=r["path"],
                    target_type="file",
                    score=EXPLICIT_FILE_SCORE,
                    reason="explicit-mention",
                )
            )

    candidates: set[str] = set()
    for backtick, camel in _IDENT_RE.findall(prompt):
        token = (backtick or camel).strip().rstrip("()").strip()
        if 3 <= len(token) <= 80:
            candidates.add(token)

    for token in candidates:
        if token in seen_symbols:
            continue
        seen_symbols.add(token)
        rows = conn.execute(
            "SELECT s.qualname, s.name, f.path AS file_path, s.line_start "
            "FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id "
            "WHERE s.qualname = ? OR s.name = ?",
            (token, token),
        ).fetchall()
        for r in rows:
            target = f"{r['qualname']} ({r['file_path']}:{r['line_start']})"
            symbol_items.append(
                RankedItem(
                    target=target,
                    target_type="symbol",
                    score=EXPLICIT_SYMBOL_SCORE,
                    reason="explicit-mention",
                )
            )
            if r["file_path"] not in seen_files:
                file_items.append(
                    RankedItem(
                        target=r["file_path"],
                        target_type="file",
                        score=EXPLICIT_FILE_FROM_SYMBOL,
                        reason="explicit-symbol-mention",
                    )
                )

    return file_items, symbol_items


# ── Channel 3: Fuzzy symbol / file ───────────────────────────────────

FUZZY_FILE_MIN_SIM = 0.40
FUZZY_FILE_SCALE = 4.5
FUZZY_SYMBOL_MIN_SIM = 0.45
FUZZY_SYMBOL_SCALE = 5.0
FUZZY_SYMBOL_BONUS = 0.5  # symbols slightly preferred over their file

# In-channel recency: small additive bump to similarity *before* the
# threshold check, so a file modified yesterday with sim=0.38 can clear
# the 0.40 cutoff. Multiplicative `apply_freshness` still runs later for
# already-ranked winners — these are complementary.
FUZZY_RECENCY_BUMP = 0.10
FUZZY_RECENCY_DAYS = 14.0


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
        "SELECT path, embedding, mtime FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    paths = [r["path"] for r in rows]
    mtimes = [int(r["mtime"]) for r in rows]
    mat = np.asarray(
        [blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32
    )
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    now_ns = int(time.time() * 1e9)
    out: list[RankedItem] = []
    for path, sim, mtime_ns in zip(paths, sims, mtimes):
        sim_raw = float(sim)
        days_old = max(0.0, (now_ns - mtime_ns) / 1e9 / 86_400)
        bump = 0.0
        if days_old < FUZZY_RECENCY_DAYS:
            bump = FUZZY_RECENCY_BUMP * (1.0 - days_old / FUZZY_RECENCY_DAYS)
        s = sim_raw + bump
        if s < FUZZY_FILE_MIN_SIM:
            continue
        score = (s - FUZZY_FILE_MIN_SIM) * FUZZY_FILE_SCALE / (1.0 - FUZZY_FILE_MIN_SIM)
        reason = f"fuzzy:{sim_raw:.2f}"
        if bump > 0:
            reason += f"+recent{bump:.2f}"
        out.append(RankedItem(target=path, target_type="file", score=score, reason=reason))
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
