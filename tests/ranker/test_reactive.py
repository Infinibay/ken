"""Reactive channel: math + edge cases that the bug fixes address."""

from __future__ import annotations

import math

import pytest

from ken.ranker.channels import (
    EVENT_WEIGHTS,
    PATTERN_MULTIPLIERS,
    READ_REPEATED_RAW_CAP,
    reactive_scores,
)


def test_read_edit_pattern(conn, make_session, make_interaction):
    """A file read once and edited once → pattern=read_edit, ×2.0."""
    make_session()
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=2)
    items = reactive_scores(conn, "test-session", current_iteration=2)
    assert len(items) == 1
    it = items[0]
    assert it.target == "src/a.py"
    assert it.reason == "reactive:read_edit"
    # Raw = read(1.0)*decay₁ + edit(2.0)*decay₀ = 1.0*exp(-0.15) + 2.0
    expected_raw = 1.0 * math.exp(-0.15) + 2.0
    expected_final = expected_raw * PATTERN_MULTIPLIERS["read_edit"]
    assert it.score == pytest.approx(expected_final)


def test_read_repeated_does_not_grow_with_more_reads(
    conn, make_session, make_interaction
):
    """Bug fix #2: 3 reads should NOT score higher than 5 reads.

    Both have pattern=read_repeated; raw is capped to a single read's
    worth before applying the multiplier.
    """
    make_session("s3")
    for i in range(1, 4):
        make_interaction(1, event="read", target="src/x.py", iteration=i)
    items3 = reactive_scores(conn, "s3", current_iteration=3)

    make_session("s5")
    for i in range(1, 6):
        make_interaction(2, event="read", target="src/y.py", iteration=i)
    items5 = reactive_scores(conn, "s5", current_iteration=5)

    assert items3 and items5
    score3, score5 = items3[0].score, items5[0].score
    expected = READ_REPEATED_RAW_CAP * PATTERN_MULTIPLIERS["read_repeated"]
    assert score3 == pytest.approx(expected)
    assert score5 == pytest.approx(expected)
    assert score5 <= score3 + 1e-9  # never grows


def test_dismissed_filtered_out(conn, make_session, make_interaction):
    """A purely-dismissed file gets negative raw → final ≤ 0 → dropped."""
    make_session()
    make_interaction(1, event="dismissed", target="src/junk.py", iteration=1)
    items = reactive_scores(conn, "test-session", current_iteration=1)
    assert items == []


def test_iter_decay_is_clamped(conn, make_session, make_interaction):
    """Bug fix #9: an interaction at iteration > current_iteration must
    not produce exp(positive) score blow-up. Clamps at 1.0× decay.
    """
    make_session()
    make_interaction(1, event="read", target="src/a.py", iteration=99)
    items = reactive_scores(conn, "test-session", current_iteration=1)
    assert len(items) == 1
    assert items[0].score == pytest.approx(EVENT_WEIGHTS["read"] * 1.0)


def test_per_turn_decay_applies(conn, make_session, make_interaction, make_prompt):
    """Tool calls anchored to older turns get TURN_DECAY ** (distance-1)."""
    make_session()
    p1 = make_prompt(1, "first prompt", iteration=1)
    make_prompt(1, "second prompt", iteration=2)
    p3 = make_prompt(1, "third prompt", iteration=3)
    make_interaction(1, event="read", target="src/old.py",
                     iteration=1, context_id=p1)
    make_interaction(1, event="read", target="src/new.py",
                     iteration=3, context_id=p3)

    items = reactive_scores(conn, "test-session", current_iteration=3)
    by_target = {it.target: it for it in items}
    assert by_target["src/new.py"].score > by_target["src/old.py"].score
