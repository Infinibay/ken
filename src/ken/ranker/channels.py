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
from dataclasses import dataclass
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

    out: list[RankedItem] = []
    for path, val in accum.items():
        score = min(PREDICTIVE_CAP, val * PREDICTIVE_SCALE)
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


LEXICAL_FILE_MIN_OVERLAP = 1
LEXICAL_SYMBOL_MIN_OVERLAP = 1
LEXICAL_FILE_SCALE = 1.4
LEXICAL_SYMBOL_SCALE = 1.8
LEXICAL_EXACT_SYMBOL_BONUS = 1.0
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
    "sigue seguir continua continuar continuemos seguimos path foco extra".split()
)
_TOKEN_ALIASES = {
    "scheduler": {"sched"},
    "scheduling": {"sched"},
}


def lexical_scores(
    conn: sqlite3.Connection, prompt: str, *, agent_id: str | None = None
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Name-token fallback for prompts that describe code in plain words.

    For continuation prompts ("continue", "sigue", "resume"), merge in
    name tokens from the recent user prompts in the same active session.
    This gives coding agents useful context when the user intentionally
    avoids restating the task.
    """
    query_tokens = _name_tokens(prompt)
    reason_prefix = "lexical"
    score_bonus = 0.0
    if _should_expand_lexical_context(prompt, query_tokens, agent_id):
        context_tokens = _recent_session_prompt_tokens(conn, agent_id or "", prompt)
        if context_tokens:
            query_tokens |= context_tokens
            reason_prefix = "lexical-context"
            score_bonus = CONTEXTUAL_LEXICAL_BONUS
    if not query_tokens:
        return [], []
    return (
        _lexical_files(conn, query_tokens, reason_prefix=reason_prefix, score_bonus=score_bonus),
        _lexical_symbols(conn, query_tokens, reason_prefix=reason_prefix, score_bonus=score_bonus),
    )


def _should_expand_lexical_context(
    prompt: str, query_tokens: set[str], agent_id: str | None
) -> bool:
    if not agent_id:
        return False
    return not query_tokens or _CONTINUATION_RE.search(prompt) is not None


def _recent_session_prompt_tokens(
    conn: sqlite3.Connection, agent_id: str, current_prompt: str
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
        tokens.update(_name_tokens(content))
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
) -> list[RankedItem]:
    rows = conn.execute("SELECT path FROM ci_files").fetchall()
    out: list[RankedItem] = []
    for row in rows:
        path = row["path"]
        tokens = _name_tokens(path)
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
) -> list[RankedItem]:
    rows = conn.execute(
        """
        SELECT s.qualname, s.name, s.line_start, f.path AS file_path
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        """
    ).fetchall()
    out: list[RankedItem] = []
    for row in rows:
        tokens = _name_tokens(f"{row['qualname']} {row['name']}")
        overlap = query_tokens & tokens
        if len(overlap) < LEXICAL_SYMBOL_MIN_OVERLAP:
            continue
        exact_name = str(row["name"]).strip("_").lower()
        exact_bonus = LEXICAL_EXACT_SYMBOL_BONUS if exact_name in query_tokens else 0.0
        score = min(
            LEXICAL_SYMBOL_SCALE + LEXICAL_EXACT_SYMBOL_BONUS + score_bonus,
            0.8 + 0.5 * len(overlap) + exact_bonus + score_bonus,
        )
        reason = f"{reason_prefix}:{','.join(sorted(overlap)[:3])}"
        if exact_bonus:
            reason += "+exact"
        out.append(
            RankedItem(
                target=f"{row['qualname']} ({row['file_path']}:{row['line_start']})",
                target_type="symbol",
                score=score,
                reason=reason,
            )
        )
    return out


def _name_tokens(text: str) -> set[str]:
    parts: set[str] = set()
    for raw in _WORD_RE.findall(text.replace("-", "_").replace(".", "_").replace("/", "_")):
        for piece in raw.split("_"):
            parts.update(_split_camel(piece))
    tokens = {p.lower() for p in parts if len(p) >= 3 and p.lower() not in _STOPWORDS}
    for token in list(tokens):
        tokens.update(_TOKEN_ALIASES.get(token, set()))
    return tokens


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
    out: list[RankedItem] = []
    for path, sim, mtime_ns in zip(paths, sims, mtimes):
        sim_raw = float(sim)
        bump = _recency_bump(mtime_ns, now_ns)
        # Clamp to 1.0 — overshoot would push the linear-mapped score
        # past FUZZY_FILE_SCALE and break the "max ≈ scale" invariant.
        s = min(1.0, sim_raw + bump)
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

    out: list[RankedItem] = []
    for r, sim in zip(rows, sims):
        sim_raw = float(sim)
        bump = _recency_bump(int(r["file_mtime"]), now_ns)
        s = min(1.0, sim_raw + bump)
        if s < FUZZY_SYMBOL_MIN_SIM:
            continue
        # Score similarly to files but a bit tighter and bonused: a hit
        # at sim 0.6 lands at ~3 (vs the file's ~2.7).
        score = (s - FUZZY_SYMBOL_MIN_SIM) * FUZZY_SYMBOL_SCALE / (1.0 - FUZZY_SYMBOL_MIN_SIM) + FUZZY_SYMBOL_BONUS
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
