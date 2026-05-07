"""Predictive channel: cap + raw-score consumption."""

from __future__ import annotations

import pytest

from ken.ranker.channels import (
    PATTERN_MULTIPLIERS,
    PREDICTIVE_CAP,
    SimilarPrompt,
    predictive_scores,
    similar_past_sessions,
)


def _insert_session_score(conn, session_id, target, score, pattern):
    conn.execute(
        "INSERT INTO cr_session_scores(session_id, target_kind, target_path, "
        "score, pattern, created_at) VALUES (?, 'file', ?, ?, ?, 0)",
        (session_id, target, score, pattern),
    )


def test_no_similar_returns_empty(conn):
    """When the similar-list is empty, predictive doesn't fire."""
    items = predictive_scores(conn, similar=[])
    assert items == []


def test_predictive_applies_pattern_mult_to_raw_score(conn, make_session):
    """Bug fix #1: cr_session_scores stores raw; predictive applies mult."""
    sess = make_session("past")
    # Stored raw=2.0 (the volume), pattern=read_edit (mult=2.0).
    _insert_session_score(conn, sess, "src/a.py", 2.0, "read_edit")
    similar = [SimilarPrompt(session_id=sess, sim=0.9, days_ago=0.0)]
    items = predictive_scores(conn, similar=similar)
    assert len(items) == 1
    # contribution = sim² * decay = 0.81 * 1.0 = 0.81
    # accum = 0.81 * 2.0(raw) * 2.0(mult) = 3.24
    # score = 3.24 * PREDICTIVE_SCALE(4.0) = 12.96 → capped to 6.0
    assert items[0].score == pytest.approx(PREDICTIVE_CAP)


def test_predictive_below_cap_uses_raw_value(conn, make_session):
    """A weak similar match should produce a small score (no cap)."""
    sess = make_session("past")
    _insert_session_score(conn, sess, "src/a.py", 0.5, "neutral")
    similar = [SimilarPrompt(session_id=sess, sim=0.5, days_ago=0.0)]
    items = predictive_scores(conn, similar=similar)
    assert len(items) == 1
    # 0.25 * 1.0 * 0.5 * 1.0 * 4.0 = 0.5
    assert items[0].score == pytest.approx(0.5)


def test_similar_past_sessions_filters_by_threshold(conn, make_session, make_prompt, fake_emb):
    """Only past prompts above SIMILAR_MIN_SIM (0.45) come back."""
    sess = make_session("past")
    make_prompt(sess, "fix auth bug", iteration=1)
    # Query with the same text → cosine = 1.0 (deterministic from fake_emb).
    similar = similar_past_sessions(conn, fake_emb("fix auth bug"))
    assert len(similar) == 1
    assert similar[0].sim == pytest.approx(1.0)
    # A different prompt → uncorrelated → below threshold.
    similar2 = similar_past_sessions(conn, fake_emb("totally unrelated text"))
    assert similar2 == []


def test_predictive_cap_with_many_sessions(conn, make_session):
    """Bug fix #5: many cooccurring sessions can't push past PREDICTIVE_CAP."""
    similar = []
    for i in range(20):
        sess = make_session(f"past-{i}")
        _insert_session_score(conn, sess, "src/popular.py", 5.0, "cited")
        similar.append(SimilarPrompt(session_id=sess, sim=0.9, days_ago=0.0))
    items = predictive_scores(conn, similar=similar)
    assert len(items) == 1
    assert items[0].score == pytest.approx(PREDICTIVE_CAP)
    assert items[0].score <= PREDICTIVE_CAP + 1e-9
