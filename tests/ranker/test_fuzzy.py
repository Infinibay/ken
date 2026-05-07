"""Fuzzy channel: cosine sweep + recency bump on files and symbols."""

from __future__ import annotations

import time

import numpy as np
import pytest

from ken.ranker.channels import (
    FUZZY_FILE_MIN_SIM,
    FUZZY_FILE_SCALE,
    FUZZY_RECENCY_BUMP,
    FUZZY_RECENCY_DAYS,
    FUZZY_SYMBOL_BONUS,
    FUZZY_SYMBOL_MIN_SIM,
    FUZZY_SYMBOL_SCALE,
    _recency_bump,
    fuzzy_scores,
    lexical_scores,
)


# ── _recency_bump ────────────────────────────────────────────────────


def test_recency_bump_recent_max():
    now_ns = int(time.time() * 1e9)
    bump = _recency_bump(now_ns, now_ns)
    assert bump == pytest.approx(FUZZY_RECENCY_BUMP)


def test_recency_bump_zero_for_old():
    now_ns = int(time.time() * 1e9)
    old_ns = now_ns - int((FUZZY_RECENCY_DAYS + 1) * 86_400 * 1e9)
    assert _recency_bump(old_ns, now_ns) == 0.0


def test_recency_bump_linear_midpoint():
    now_ns = int(time.time() * 1e9)
    half_ns = now_ns - int((FUZZY_RECENCY_DAYS / 2) * 86_400 * 1e9)
    bump = _recency_bump(half_ns, now_ns)
    assert bump == pytest.approx(FUZZY_RECENCY_BUMP * 0.5, rel=0.05)


# ── fuzzy_scores files ──────────────────────────────────────────────


def test_fuzzy_files_high_similarity_scores(conn, make_file, fake_emb):
    make_file("src/auth.py")
    # Embed query identical to file's embedding text → cosine = 1.0
    q = fake_emb("src/auth.py")
    files, _ = fuzzy_scores(conn, q)
    assert len(files) == 1
    assert files[0].target == "src/auth.py"
    # sim=1.0 → score = (1.0 - MIN) * SCALE / (1.0 - MIN) = SCALE.
    # Plus tiny recency bump (file is "now"), but we clamp to 1.0 first.
    assert files[0].score == pytest.approx(FUZZY_FILE_SCALE)
    assert "fuzzy:" in files[0].reason


def test_fuzzy_files_below_threshold_dropped(conn, make_file, fake_emb):
    """A file embedded for one term, queried with an unrelated term, should
    sit below the 0.40 threshold and get dropped."""
    make_file("src/auth.py", days_old=30.0)  # old → no recency bump
    q = fake_emb("totally unrelated topic")
    files, _ = fuzzy_scores(conn, q)
    assert files == []


def test_fuzzy_files_recency_clamps_to_one(conn, make_file, fake_emb):
    """Even with a recency bump, the effective sim is clamped at 1.0 so
    score ≤ FUZZY_FILE_SCALE — the contract callers rely on."""
    make_file("src/auth.py")  # days_old=0 → max bump
    q = fake_emb("src/auth.py")  # sim=1.0
    files, _ = fuzzy_scores(conn, q)
    assert len(files) == 1
    assert files[0].score <= FUZZY_FILE_SCALE + 1e-9


def test_fuzzy_files_empty_when_no_embeddings(conn):
    """No ci_files rows with embeddings → empty result, no crash."""
    files, syms = fuzzy_scores(conn, np.zeros(384, dtype=np.float32))
    assert files == []
    assert syms == []


# ── fuzzy_scores symbols ────────────────────────────────────────────


def test_fuzzy_symbols_with_bonus(conn, make_file, make_symbol, fake_emb):
    fid = make_file("src/auth.py")
    make_symbol(fid, name="login", qualname="login", line_start=10)
    q = fake_emb("login")  # cosine = 1.0 with the symbol embedding
    _, syms = fuzzy_scores(conn, q)
    assert len(syms) == 1
    # sim=1.0 maps to FUZZY_SYMBOL_SCALE + FUZZY_SYMBOL_BONUS.
    assert syms[0].score == pytest.approx(FUZZY_SYMBOL_SCALE + FUZZY_SYMBOL_BONUS)
    assert "login" in syms[0].target


def test_fuzzy_symbols_threshold_higher_than_files(conn, make_file, make_symbol, fake_emb):
    """FUZZY_SYMBOL_MIN_SIM > FUZZY_FILE_MIN_SIM — a marginal match drops out
    of symbols but might still be above the file cutoff."""
    assert FUZZY_SYMBOL_MIN_SIM > FUZZY_FILE_MIN_SIM
    fid = make_file("src/auth.py", days_old=30.0)
    make_symbol(fid, name="zzz_obscure_symbol", qualname="zzz_obscure_symbol")
    q = fake_emb("an entirely different prompt")  # uncorrelated
    _, syms = fuzzy_scores(conn, q)
    assert syms == []


def test_fuzzy_symbols_target_includes_path_and_line(conn, make_file, make_symbol, fake_emb):
    fid = make_file("src/auth.py")
    make_symbol(fid, name="Session", qualname="Session", line_start=42)
    q = fake_emb("Session")
    _, syms = fuzzy_scores(conn, q)
    assert len(syms) == 1
    # Contract: target = "qualname (path:line)"
    assert syms[0].target == "Session (src/auth.py:42)"


# ── lexical_scores ──────────────────────────────────────────────────


def test_lexical_files_match_name_tokens(conn, make_file):
    make_file("src/ken/codex_hooks_template.py")

    files, syms = lexical_scores(conn, "repair codex hook wiring")

    assert syms == []
    assert len(files) == 1
    assert files[0].target == "src/ken/codex_hooks_template.py"
    assert "lexical:codex" in files[0].reason


def test_lexical_symbols_match_camelcase_tokens(conn, make_file, make_symbol):
    fid = make_file("src/ken/status.py")
    make_symbol(fid, name="StatusCounts", qualname="StatusCounts", line_start=12)

    _, syms = lexical_scores(conn, "status counts diagnostics")

    assert len(syms) == 1
    assert syms[0].target == "StatusCounts (src/ken/status.py:12)"
    assert "lexical:" in syms[0].reason


def test_lexical_ignores_stopwords(conn, make_file):
    make_file("src/ken/status.py")

    files, syms = lexical_scores(conn, "what is the function")

    assert files == []
    assert syms == []


def test_lexical_continuation_uses_recent_session_prompt(
    conn, make_session, make_prompt, make_file
):
    sess = make_session("alpha")
    make_prompt(sess, "improve codex hook wiring")
    make_prompt(sess, "sigue tu path")
    make_file("src/ken/codex_hooks_template.py")

    files, syms = lexical_scores(conn, "sigue tu path", agent_id="alpha")

    assert syms == []
    assert len(files) == 1
    assert files[0].target == "src/ken/codex_hooks_template.py"
    assert "lexical-context:codex" in files[0].reason


def test_lexical_specific_prompt_does_not_inherit_recent_session_prompt(
    conn, make_session, make_prompt, make_file
):
    sess = make_session("alpha")
    make_prompt(sess, "improve codex hook wiring")
    make_file("src/ken/codex_hooks_template.py")

    files, syms = lexical_scores(conn, "status diagnostics", agent_id="alpha")

    assert files == []
    assert syms == []
