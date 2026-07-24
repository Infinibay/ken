"""The three independent scoring channels.

Each function takes a sqlite3 connection (read-only is fine) and
returns a list of ``RankedItem``. Keys are file paths or symbol
qualnames; the merge step in ``ranker.merge`` reconciles them.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ken.embedder import blob_to_vec
from ken.ranker import FindingItem, RankedItem

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

# Pattern → multiplier. Productivity weight applied on top of the raw
# event sum. Note that ``cited`` already carries 2.5 in EVENT_WEIGHTS,
# so we keep its pattern multiplier modest (1.5) — otherwise a single
# transcript citation would compound to 6.25 (2.5 × 2.5) and tower
# over read_edit.
PATTERN_MULTIPLIERS = {
    "cited": 1.5,
    "read_edit": 2.0,
    "edit_only": 1.5,
    "neutral": 1.0,
    "read_repeated": 0.7,
    "read_skipped": 0.3,
    "dismissed": 0.3,
}

# When pattern is read_repeated we cap raw to a single read's worth
# *before* applying the multiplier — otherwise N reads → N×0.7 gives
# higher scores the more confused the session was, contradicting the
# pattern's intent.
READ_REPEATED_RAW_CAP = 1.0  # = EVENT_WEIGHTS["read"]


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
        # Clamp at 0 in case of any race that gave us iteration > current —
        # exp(positive) would otherwise blow the score up.
        iter_decay = math.exp(-LAMBDA * max(0, current_iteration - iteration))
        turn_mult = _turn_multiplier(row["context_id"], turn_rank, latest_turn)
        raw[path] += base * iter_decay * turn_mult
        events[path].append(event_type)
        if event_type in {"edit", "edited"}:
            edited_targets.add(path)

    out: list[RankedItem] = []
    for path, raw_score in raw.items():
        pattern = _classify_pattern(events[path], edited_elsewhere=any(t != path for t in edited_targets))
        capped_raw = (
            min(raw_score, READ_REPEATED_RAW_CAP)
            if pattern == "read_repeated"
            else raw_score
        )
        final = capped_raw * PATTERN_MULTIPLIERS.get(pattern, 1.0)
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


# ── Similar-prompt search (shared by predictive + dismissal boost) ───
#
# Computing cosine similarity over recent user prompts is expensive
# enough that we want to do it once per rank() and share the result
# between the predictive channel and the dismissal-penalty boost.

PREDICTIVE_TOP_PROMPTS = 50
SIMILAR_MIN_SIM = 0.45


@dataclass(frozen=True)
class SimilarPrompt:
    """A past user_prompt close enough in embedding-space to matter."""

    session_id: int
    sim: float
    days_ago: float


def similar_past_sessions(
    conn: sqlite3.Connection,
    prompt_embedding: np.ndarray,
    *,
    top: int = PREDICTIVE_TOP_PROMPTS,
    threshold: float = SIMILAR_MIN_SIM,
) -> list[SimilarPrompt]:
    rows = conn.execute(
        """
        SELECT session_id, embedding, created_at
        FROM cr_contexts
        WHERE kind = 'user_prompt' AND embedding IS NOT NULL
        ORDER BY created_at DESC LIMIT ?
        """,
        (top,),
    ).fetchall()
    if not rows:
        return []
    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)
    now_ms = _now_ms(conn)
    out: list[SimilarPrompt] = []
    for r in rows:
        v = blob_to_vec(r["embedding"])
        sim = float(np.dot(q, v / (np.linalg.norm(v) + 1e-12)))
        if sim < threshold:
            continue
        days_ago = max(0.0, (now_ms - int(r["created_at"])) / (1000 * 60 * 60 * 24))
        out.append(SimilarPrompt(int(r["session_id"]), sim, days_ago))
    return out


# ── Popularity discount (lift / PMI, Phase 3) ────────────────────────
#
# Predictive and co-occurrence evidence both suffer from popularity bias:
# a file touched in nearly every session (``cli.py``, ``db.py``) accrues
# evidence for *any* prompt. We discount each file's accumulated evidence
# by its global base rate — the numerator (similar-session evidence) over
# a denominator (how universal the file is) is exactly a lift/PMI signal.
# Gated behind KEN_RANKER_LIFT so it can be measured in isolation.

LIFT_BETA = 4.0          # discount strength: ubiquitous file → ~1/(1+β)
LIFT_MIN_SESSIONS = 5    # below this we have no base-rate estimate → neutral


def lift_enabled() -> bool:
    return os.environ.get("KEN_RANKER_LIFT", "").strip().lower() in {
        "1", "true", "on", "yes",
    }


def file_base_rates(conn: sqlite3.Connection) -> tuple[int, dict[str, int]]:
    """Return ``(n_sessions, {path: document_frequency})`` over snapshots.

    ``document_frequency`` = number of distinct sessions in which the file
    had a positive productivity score.
    """
    n_row = conn.execute(
        "SELECT COUNT(DISTINCT session_id) AS n FROM cr_session_scores"
    ).fetchone()
    n = int(n_row["n"]) if n_row and n_row["n"] is not None else 0
    df: dict[str, int] = {}
    if n:
        for r in conn.execute(
            "SELECT target_path, COUNT(DISTINCT session_id) AS df "
            "FROM cr_session_scores "
            "WHERE score > 0 AND target_path IS NOT NULL GROUP BY target_path"
        ):
            df[str(r["target_path"])] = int(r["df"])
    return n, df


def base_rate_discount(n: int, df: dict[str, int], path: str) -> float:
    """Multiplicative discount in (0, 1]; 1.0 for rare, →1/(1+β) for ubiquitous."""
    if n < LIFT_MIN_SESSIONS:
        return 1.0
    base = (df.get(path, 0) + 1.0) / (n + 2.0)  # Laplace-smoothed P(f | all)
    return 1.0 / (1.0 + LIFT_BETA * base)


# ── Channel 2: Predictive ────────────────────────────────────────────

PREDICTIVE_DECAY_DAYS = 14.0
PREDICTIVE_SCALE = 4.0
# Hard cap so a file co-occurring across many similar past sessions
# can't dominate fuzzy/reactive (which max out near ~5–6).
PREDICTIVE_CAP = 6.0


def predictive_scores(
    conn: sqlite3.Connection, similar: list[SimilarPrompt]
) -> list[RankedItem]:
    """Score files by what past similar-prompt sessions ended up using.

    *similar* is the precomputed list from :func:`similar_past_sessions`
    so we don't redo the cosine sweep here. Session scores are pulled
    in a single grouped fetch; we then iterate per-similar-prompt to
    accumulate ``sim² × decay × stored_raw_score × pattern_mult``.

    Important: ``cr_session_scores.score`` now stores the *raw*
    productivity volume from the snapshot (no pattern multiplier
    applied). The multiplier is applied here at consumption — that way
    persisted history doesn't double-count when a hot-pattern session
    feeds future ranks.
    """
    if not similar:
        return []
    sess_ids = list({sp.session_id for sp in similar})
    placeholders = ",".join("?" * len(sess_ids))
    score_rows = conn.execute(
        f"""
        SELECT session_id, target_path, score, pattern
        FROM cr_session_scores
        WHERE session_id IN ({placeholders})
          AND target_kind = 'file' AND target_path IS NOT NULL
        """,
        sess_ids,
    ).fetchall()
    if not score_rows:
        return []
    by_session: dict[int, list[Any]] = defaultdict(list)
    for sr in score_rows:
        by_session[int(sr["session_id"])].append(sr)

    accum: dict[str, float] = defaultdict(float)
    for sp in similar:
        decay = math.exp(-sp.days_ago / PREDICTIVE_DECAY_DAYS)
        contribution = sp.sim * sp.sim * decay  # sim² rewards confident matches
        for sr in by_session.get(sp.session_id, ()):
            mult = PATTERN_MULTIPLIERS.get(sr["pattern"], 1.0)
            accum[sr["target_path"]] += contribution * float(sr["score"]) * mult

    use_lift = lift_enabled()
    if use_lift:
        n_sessions, df = file_base_rates(conn)

    out: list[RankedItem] = []
    for path, val in accum.items():
        reason = "predictive"
        if use_lift:
            discount = base_rate_discount(n_sessions, df, path)
            val *= discount
            if discount < 0.99:
                reason = f"predictive×lift{discount:.2f}"
        score = min(PREDICTIVE_CAP, val * PREDICTIVE_SCALE)
        if score > 0:
            out.append(RankedItem(target=path, target_type="file", score=score, reason=reason))
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
_TRACEBACK_FILE_RE = re.compile(
    r'File "([^"\n]+)", line (\d+)|File\s+([\w./\-]+\.[a-zA-Z]{1,5})\s+line\s+(\d+)'
)
# Either backtick-quoted (group 1) or a CamelCase / Class.method
# identifier in plain prose (group 2). Lowercase identifiers without
# backticks are too noisy ("the function" → "the").
_IDENT_RE = re.compile(r"`([^`\n]+)`|\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\b")
_SNAKE_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b")

_KNOWN_EXTS = frozenset(
    "py pyi rs js jsx mjs cjs ts tsx go java md rst json yaml yml toml sh sql html css".split()
)

EXPLICIT_FILE_SCORE = 5.0
EXPLICIT_SYMBOL_SCORE = 5.5
EXPLICIT_FILE_FROM_SYMBOL = 3.5  # symbol named → boost its file too, but less
EXPLICIT_LINE_SYMBOL_SCORE = 6.0


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
        parts = m.split(":")
        base = parts[0]
        line_no = _line_number(parts[1]) if len(parts) > 1 else None
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
            if line_no is not None:
                _append_symbols_at_line(
                    conn, symbol_items, seen_symbols, r["path"], line_no
                )

    for quoted_path, quoted_line, bare_path, bare_line in _TRACEBACK_FILE_RE.findall(prompt):
        base = quoted_path or bare_path
        raw_line = quoted_line or bare_line
        line_no = _line_number(raw_line)
        if line_no is None:
            continue
        ext = base.rsplit(".", 1)[-1].lower()
        if ext not in _KNOWN_EXTS:
            continue
        rows = conn.execute(
            "SELECT path FROM ci_files WHERE path = ? OR path LIKE ?",
            (base, f"%/{base}"),
        ).fetchall()
        for r in rows:
            if r["path"] not in seen_files:
                seen_files.add(r["path"])
                file_items.append(
                    RankedItem(
                        target=r["path"],
                        target_type="file",
                        score=EXPLICIT_FILE_SCORE,
                        reason="explicit-mention",
                    )
                )
            _append_symbols_at_line(conn, symbol_items, seen_symbols, r["path"], line_no)

    candidates: set[str] = set()
    for backtick, camel in _IDENT_RE.findall(prompt):
        token = (backtick or camel).strip().rstrip("()").strip()
        if 3 <= len(token) <= 80:
            candidates.add(token)
    for token in _SNAKE_IDENT_RE.findall(prompt):
        token = token.strip().rstrip("()").strip()
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


def _line_number(raw: str) -> int | None:
    try:
        return int(raw.split("-", 1)[0])
    except ValueError:
        return None


def _append_symbols_at_line(
    conn: sqlite3.Connection,
    symbol_items: list[RankedItem],
    seen_symbols: set[str],
    path: str,
    line_no: int,
) -> None:
    rows = conn.execute(
        """
        SELECT s.qualname, s.line_start, f.path AS file_path
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE f.path = ? AND s.line_start <= ? AND s.line_end >= ?
        ORDER BY (s.line_end - s.line_start), s.line_start
        LIMIT 2
        """,
        (path, line_no, line_no),
    ).fetchall()
    for r in rows:
        target = f"{r['qualname']} ({r['file_path']}:{r['line_start']})"
        if target in seen_symbols:
            continue
        seen_symbols.add(target)
        symbol_items.append(
            RankedItem(
                target=target,
                target_type="symbol",
                score=EXPLICIT_LINE_SYMBOL_SCORE,
                reason="explicit-line-mention",
            )
        )


# ── Adaptive per-query thresholds (Phase 2) ──────────────────────────
#
# Absolute cosine floors (0.40/0.42/0.45) assume a stable similarity
# distribution. A different embedder (multilingual) or a cross-language
# prompt shifts the whole distribution, so a fixed floor either floods or
# starves. The adaptive threshold is relative to *this query's* similarity
# distribution: keep items above μ+kσ, clamped so it only ever LOWERS the
# fixed floor for weak-signal queries (never raises it — strong in-domain
# queries keep current behaviour). The effective threshold is also used as
# the score-mapping anchor, so surfaced items score sensibly on the
# lowered scale. Gated behind KEN_RANKER_ADAPTIVE.

ADAPTIVE_FLOOR = 0.22    # absolute safety net once thresholds go relative
ADAPTIVE_K = 1.5         # keep items ≥ μ + K·σ of the query distribution


def adaptive_enabled() -> bool:
    return os.environ.get("KEN_RANKER_ADAPTIVE", "").strip().lower() in {
        "1", "true", "on", "yes",
    }


def _adaptive_threshold(sims: "np.ndarray", fixed_min: float) -> float:
    if not adaptive_enabled() or sims.size == 0:
        return fixed_min
    mu = float(sims.mean())
    sd = float(sims.std())
    relative = mu + ADAPTIVE_K * sd
    # Only lower the fixed floor (weak-signal queries); never raise it.
    return min(fixed_min, max(ADAPTIVE_FLOOR, relative))


# ── Channel 3: Fuzzy symbol / file ───────────────────────────────────

FUZZY_FILE_MIN_SIM = 0.40
FUZZY_FILE_SCALE = 4.5
FUZZY_SYMBOL_MIN_SIM = 0.45
FUZZY_SYMBOL_SCALE = 5.0
FUZZY_SYMBOL_BONUS = 0.5  # symbols slightly preferred over their file
DOC_INTENT_MIN_SIM = 0.42
DOC_INTENT_FILE_SCALE = 3.2
DOC_INTENT_SYMBOL_SCALE = 3.6

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


def doc_intent_scores(
    conn: sqlite3.Connection, prompt_embedding: np.ndarray
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Score files/symbols by explicit purpose text such as docstrings."""
    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)
    rows = conn.execute(
        """
        SELECT i.source_kind, i.text, i.embedding, i.weight,
               f.path AS file_path,
               s.qualname, s.line_start
        FROM ci_intent_sources i
        JOIN ci_files f ON f.id = i.file_id
        LEFT JOIN ci_symbols s ON s.id = i.symbol_id
        WHERE i.embedding IS NOT NULL
        """
    ).fetchall()
    if not rows:
        return [], []

    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    thr = _adaptive_threshold(sims, DOC_INTENT_MIN_SIM)
    file_scores: dict[str, RankedItem] = {}
    symbol_scores: dict[str, RankedItem] = {}
    for row, sim in zip(rows, sims):
        sim_raw = float(sim)
        if sim_raw < thr:
            continue
        target_path = str(row["file_path"])
        weight = float(row["weight"])
        source_kind = str(row["source_kind"])
        if row["qualname"] is None:
            score = (
                (sim_raw - thr)
                * DOC_INTENT_FILE_SCALE
                / (1.0 - thr)
                * weight
            )
            _keep_best(
                file_scores,
                target_path,
                RankedItem(
                    target=target_path,
                    target_type="file",
                    score=score,
                    reason=f"doc-intent:{source_kind}:{sim_raw:.2f}",
                ),
            )
        else:
            target = f"{row['qualname']} ({target_path}:{row['line_start']})"
            score = (
                (sim_raw - thr)
                * DOC_INTENT_SYMBOL_SCALE
                / (1.0 - thr)
                * weight
            )
            _keep_best(
                symbol_scores,
                target,
                RankedItem(
                    target=target,
                    target_type="symbol",
                    score=score,
                    reason=f"doc-intent:{source_kind}:{sim_raw:.2f}",
                ),
            )
            _keep_best(
                file_scores,
                target_path,
                RankedItem(
                    target=target_path,
                    target_type="file",
                    score=score * 0.65,
                    reason=f"doc-intent-symbol:{source_kind}:{sim_raw:.2f}",
                ),
            )
    return list(file_scores.values()), list(symbol_scores.values())


def _keep_best(items: dict[str, RankedItem], key: str, candidate: RankedItem) -> None:
    current = items.get(key)
    if current is None or candidate.score > current.score:
        items[key] = candidate


# ── Literal content tokens ───────────────────────────────────────────

LITERAL_FILE_MIN_OVERLAP = 1
LITERAL_FILE_SCALE = 0.45
LITERAL_FILE_BASE = 1.15
LITERAL_FILE_MAX_SCORE = 2.5
LITERAL_MAX_FILE_BYTES = 256 * 1024
_LITERAL_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}")
_LITERAL_PAIR_LEFT = frozenset(
    {"case", "context", "expected", "file", "max", "min", "num", "rank", "top"}
)
_LITERAL_PAIR_RIGHT = frozenset(
    {
        "chars",
        "count",
        "findings",
        "files",
        "id",
        "limit",
        "line",
        "path",
        "rank",
        "recall",
        "size",
        "symbols",
        "tokens",
    }
)


def literal_content_scores(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    project_root: Path | None = None,
) -> list[RankedItem]:
    """Score files containing exact rare/API-like prompt tokens.

    Embeddings and name tokens often miss stringly contracts such as
    ``exec_command``, ``apply_patch``, env vars, matcher names, and
    protocol constants. Exact literal matching is only used for those
    high-signal tokens and only when a live project root is available.
    """
    if project_root is None:
        return []
    tokens = _literal_tokens(prompt)
    if not tokens:
        return []
    rows = conn.execute("SELECT path FROM ci_files").fetchall()
    root = project_root.resolve()
    out: list[RankedItem] = []
    for row in rows:
        path = str(row["path"])
        if not _literal_candidate_path(path):
            continue
        abs_path = root / path
        try:
            if not abs_path.is_file() or abs_path.stat().st_size > LITERAL_MAX_FILE_BYTES:
                continue
            text = abs_path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        overlap = {token for token in tokens if token.lower() in text}
        if len(overlap) < LITERAL_FILE_MIN_OVERLAP:
            continue
        score = min(
            LITERAL_FILE_MAX_SCORE,
            LITERAL_FILE_BASE + LITERAL_FILE_SCALE * len(overlap),
        )
        out.append(
            RankedItem(
                target=path,
                target_type="file",
                score=score,
                reason=f"literal:{','.join(sorted(overlap)[:3])}",
            )
        )
    return out


def _literal_candidate_path(path: str) -> bool:
    # Labeled benchmark fixtures intentionally repeat task prompts; if
    # literal matching indexes them, the evaluator starts retrieving its
    # own answer key instead of the implementation surface.
    if path.startswith("examples/bench/"):
        return False
    return True


def _literal_tokens(prompt: str) -> set[str]:
    raw_list = [
        token.strip("`'\"()[]{}").lower()
        for token in _LITERAL_TOKEN_RE.findall(prompt)
    ]
    raw = set(raw_list)
    out: set[str] = set()
    for token in raw:
        if len(token) < 4 or token in _STOPWORDS:
            continue
        if "_" in token or "." in token or "-" in token:
            out.add(token)
    meaningful = [
        token
        for token in raw_list
        if len(token) >= 3 and token not in _STOPWORDS
    ]
    for left, right in zip(meaningful, meaningful[1:]):
        if len(left) < 3 or len(right) < 3:
            continue
        if left not in _LITERAL_PAIR_LEFT and right not in _LITERAL_PAIR_RIGHT:
            continue
        out.add(f"{left}_{right}")
        out.add(f"{left}-{right}")
    return out


LEXICAL_FILE_MIN_OVERLAP = 1
LEXICAL_SYMBOL_MIN_OVERLAP = 1
LEXICAL_FILE_SCALE = 1.4
LEXICAL_SYMBOL_SCALE = 1.8
LEXICAL_EXACT_SYMBOL_BONUS = 1.0
LEXICAL_KIND_BONUS = 1.2
LEXICAL_GENERIC_EXACT_SYMBOLS = frozenset(
    {"chars", "class", "code", "context", "file", "source", "stats", "test"}
)
CONTEXTUAL_LEXICAL_RECENT_PROMPTS = 3
CONTEXTUAL_LEXICAL_BONUS = 0.6
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_CONTINUATION_RE = re.compile(
    r"\b(continue|continuing|keep going|carry on|resume|sigue|seguir|continua|"
    r"continuar|contin[uú]a|segu[ií]|seguimos)\b",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    "the and for with from into this that what where when why how fix bug error "
    "traceback file line test tests code src function class method module "
    "este esta esto ese esa eso con para que por los las una uno momento ahora "
    "sigue seguir continua continuar continuemos seguimos path foco extra cual "
    "quien donde cuando como clase codigo código fichero archivo funcion función".split()
)
_TOKEN_ALIASES = {
    "class": {"class"},
    "code": {"code"},
    "file": {"file"},
    "scheduler": {"sched"},
    "scheduling": {"sched"},
    "parsear": {"parse", "parser", "parsers", "parsed"},
    "parsea": {"parse", "parser", "parsers", "parsed"},
    "parseo": {"parse", "parser", "parsers", "parsed"},
    "parse": {"parser", "parsers", "parsed"},
    "parser": {"parse", "parsers", "parsed"},
    "parsing": {"parse", "parser", "parsers", "parsed"},
    "archivo": {"file", "source"},
    "fichero": {"file", "source"},
    "codigo": {"code", "source"},
    "código": {"code", "source"},
    "clase": {"class"},
}


def lexical_scores(
    conn: sqlite3.Connection,
    prompt: str,
    *,
    agent_id: str | None = None,
    project_root: Path | None = None,
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Name-token fallback for prompts that describe code in plain words.

    For continuation prompts ("continue", "sigue", "resume"), merge in
    name tokens from the recent user prompts in the same active session.
    This gives coding agents useful context when the user intentionally
    avoids restating the task.
    """
    project_stopwords = _project_stopwords(project_root)
    query_tokens = _name_tokens(prompt, extra_stopwords=project_stopwords)
    reason_prefix = "lexical"
    score_bonus = 0.0
    if _should_expand_lexical_context(prompt, query_tokens, agent_id):
        context_tokens = _recent_session_prompt_tokens(
            conn,
            agent_id or "",
            prompt,
            extra_stopwords=project_stopwords,
        )
        if context_tokens:
            query_tokens |= context_tokens
            reason_prefix = "lexical-context"
            score_bonus = CONTEXTUAL_LEXICAL_BONUS
    if not query_tokens:
        return [], []
    return (
        _lexical_files(
            conn,
            query_tokens,
            reason_prefix=reason_prefix,
            score_bonus=score_bonus,
            extra_stopwords=project_stopwords,
        ),
        _lexical_symbols(
            conn,
            query_tokens,
            reason_prefix=reason_prefix,
            score_bonus=score_bonus,
            extra_stopwords=project_stopwords,
        ),
    )


def _should_expand_lexical_context(
    prompt: str, query_tokens: set[str], agent_id: str | None
) -> bool:
    if not agent_id:
        return False
    return not query_tokens or _CONTINUATION_RE.search(prompt) is not None


def _recent_session_prompt_tokens(
    conn: sqlite3.Connection,
    agent_id: str,
    current_prompt: str,
    *,
    extra_stopwords: set[str] | None = None,
) -> set[str]:
    row = conn.execute("SELECT id FROM cr_sessions WHERE agent_id = ?", (agent_id,)).fetchone()
    if row is None:
        return set()
    rows = conn.execute(
        """
        SELECT content
        FROM cr_contexts
        WHERE session_id = ? AND kind = 'user_prompt'
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(row["id"]), CONTEXTUAL_LEXICAL_RECENT_PROMPTS + 1),
    ).fetchall()
    tokens: set[str] = set()
    skipped_current = False
    used = 0
    for recent in rows:
        content = str(recent["content"])
        if not skipped_current and content == current_prompt:
            skipped_current = True
            continue
        tokens.update(_name_tokens(content, extra_stopwords=extra_stopwords))
        used += 1
        if used >= CONTEXTUAL_LEXICAL_RECENT_PROMPTS:
            break
    return tokens


def _lexical_files(
    conn: sqlite3.Connection,
    query_tokens: set[str],
    *,
    reason_prefix: str = "lexical",
    score_bonus: float = 0.0,
    extra_stopwords: set[str] | None = None,
) -> list[RankedItem]:
    rows = conn.execute("SELECT path FROM ci_files").fetchall()
    out: list[RankedItem] = []
    for row in rows:
        path = row["path"]
        tokens = _name_tokens(path, extra_stopwords=extra_stopwords)
        overlap = query_tokens & tokens
        if len(overlap) < LEXICAL_FILE_MIN_OVERLAP:
            continue
        score = min(LEXICAL_FILE_SCALE + score_bonus, 0.6 + 0.4 * len(overlap) + score_bonus)
        out.append(
            RankedItem(
                target=path,
                target_type="file",
                score=score,
                reason=f"{reason_prefix}:{','.join(sorted(overlap)[:3])}",
            )
        )
    return out


def _lexical_symbols(
    conn: sqlite3.Connection,
    query_tokens: set[str],
    *,
    reason_prefix: str = "lexical",
    score_bonus: float = 0.0,
    extra_stopwords: set[str] | None = None,
) -> list[RankedItem]:
    rows = conn.execute(
        """
        SELECT s.kind, s.qualname, s.name, s.line_start, f.path AS file_path
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        """
    ).fetchall()
    out: list[RankedItem] = []
    for row in rows:
        kind = str(row["kind"] or "")
        tokens = _name_tokens(
            f"{kind} {row['qualname']} {row['name']}",
            extra_stopwords=extra_stopwords,
        )
        overlap = query_tokens & tokens
        if len(overlap) < LEXICAL_SYMBOL_MIN_OVERLAP:
            continue
        exact_name = str(row["name"]).strip("_").lower()
        exact_bonus = (
            LEXICAL_EXACT_SYMBOL_BONUS
            if exact_name in query_tokens and exact_name not in LEXICAL_GENERIC_EXACT_SYMBOLS
            else 0.0
        )
        kind_bonus = LEXICAL_KIND_BONUS if kind.lower() in query_tokens else 0.0
        score = min(
            LEXICAL_SYMBOL_SCALE
            + LEXICAL_EXACT_SYMBOL_BONUS
            + LEXICAL_KIND_BONUS
            + score_bonus,
            0.8 + 0.5 * len(overlap) + exact_bonus + kind_bonus + score_bonus,
        )
        reason = f"{reason_prefix}:{','.join(sorted(overlap)[:3])}"
        if exact_bonus:
            reason += "+exact"
        if kind_bonus:
            reason += "+kind"
        out.append(
            RankedItem(
                target=f"{row['qualname']} ({row['file_path']}:{row['line_start']})",
                target_type="symbol",
                score=score,
                reason=reason,
            )
        )
    return out


def _name_tokens(text: str, *, extra_stopwords: set[str] | None = None) -> set[str]:
    parts: set[str] = set()
    for raw in _WORD_RE.findall(text.replace("-", "_").replace(".", "_").replace("/", "_")):
        for piece in raw.split("_"):
            parts.update(_split_camel(piece))
    raw_tokens = {p.lower() for p in parts if len(p) >= 3}
    stopwords = _STOPWORDS if not extra_stopwords else _STOPWORDS | extra_stopwords
    tokens = {p for p in raw_tokens if p not in stopwords}
    for token in raw_tokens:
        tokens.update(_TOKEN_ALIASES.get(token, set()))
    return tokens


def _project_stopwords(project_root: Path | None) -> set[str]:
    if project_root is None:
        return set()
    tokens = _name_tokens(project_root.name)
    # One-token project/package names often appear in every path
    # (e.g. src/ken/...), so lexical matching should not treat them as
    # task intent unless another channel corroborates them.
    return {token for token in tokens if len(token) >= 3}


def _split_camel(text: str) -> list[str]:
    return re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", text)


def _recency_bump(mtime_ns: int, now_ns: int) -> float:
    days_old = max(0.0, (now_ns - mtime_ns) / 1e9 / 86_400)
    if days_old >= FUZZY_RECENCY_DAYS:
        return 0.0
    return FUZZY_RECENCY_BUMP * (1.0 - days_old / FUZZY_RECENCY_DAYS)


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
    thr = _adaptive_threshold(sims, FUZZY_FILE_MIN_SIM)
    out: list[RankedItem] = []
    for path, sim, mtime_ns in zip(paths, sims, mtimes):
        sim_raw = float(sim)
        bump = _recency_bump(mtime_ns, now_ns)
        # Clamp to 1.0 — overshoot would push the linear-mapped score
        # past FUZZY_FILE_SCALE and break the "max ≈ scale" invariant.
        s = min(1.0, sim_raw + bump)
        if s < thr:
            continue
        score = (s - thr) * FUZZY_FILE_SCALE / (1.0 - thr)
        reason = f"fuzzy:{sim_raw:.2f}"
        if bump > 0:
            reason += f"+recent{bump:.2f}"
        out.append(RankedItem(target=path, target_type="file", score=score, reason=reason))
    return out


def _fuzzy_symbols(conn: sqlite3.Connection, q: np.ndarray) -> list[RankedItem]:
    rows = conn.execute(
        """
        SELECT s.qualname, s.name, s.embedding, s.line_start, f.path AS file_path,
               f.mtime AS file_mtime
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
    now_ns = int(time.time() * 1e9)
    thr = _adaptive_threshold(sims, FUZZY_SYMBOL_MIN_SIM)

    out: list[RankedItem] = []
    for r, sim in zip(rows, sims):
        sim_raw = float(sim)
        bump = _recency_bump(int(r["file_mtime"]), now_ns)
        s = min(1.0, sim_raw + bump)
        if s < thr:
            continue
        # Score similarly to files but a bit tighter and bonused: a hit
        # at sim 0.6 lands at ~3 (vs the file's ~2.7).
        score = (s - thr) * FUZZY_SYMBOL_SCALE / (1.0 - thr) + FUZZY_SYMBOL_BONUS
        target = f"{r['qualname']} ({r['file_path']}:{r['line_start']})"
        reason = f"fuzzy:{sim_raw:.2f}"
        if bump > 0:
            reason += f"+recent{bump:.2f}"
        out.append(RankedItem(target=target, target_type="symbol", score=score, reason=reason))
    return out


# ── Channel 4: Findings ─────────────────────────────────────────────

FINDING_MIN_SIM = 0.48
FINDING_SCALE = 3.5


def finding_scores(
    conn: sqlite3.Connection, prompt_embedding: np.ndarray
) -> list[FindingItem]:
    """Surface durable notes semantically close to the current prompt."""
    rows = conn.execute(
        "SELECT topic, content, tags, embedding FROM cr_findings WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    q = prompt_embedding.astype(np.float32, copy=False)
    q = q / (np.linalg.norm(q) + 1e-12)
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    out: list[FindingItem] = []
    for row, sim in zip(rows, sims):
        sim_raw = float(sim)
        if sim_raw < FINDING_MIN_SIM:
            continue
        score = (sim_raw - FINDING_MIN_SIM) * FINDING_SCALE / (1.0 - FINDING_MIN_SIM)
        out.append(
            FindingItem(
                topic=row["topic"],
                content=row["content"],
                tags=_parse_tags(row["tags"]),
                score=score,
                reason=f"finding:{sim_raw:.2f}",
            )
        )
    return out


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        import json

        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [t for t in parsed if isinstance(t, str)]
