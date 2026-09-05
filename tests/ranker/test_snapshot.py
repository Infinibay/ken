"""Snapshot persistence: ensures raw scores (not pre-multiplied) hit cr_session_scores."""

from __future__ import annotations

import pytest

from ken.ranker.channels import PATTERN_MULTIPLIERS
from ken.ranker.snapshot import snapshot_session_scores


def test_snapshot_stores_raw_score(conn, make_session, make_interaction):
    """Bug fix #1: cr_session_scores.score must NOT have the pattern
    multiplier baked in — the consumer (predictive) reapplies it.
    """
    make_session("alpha")
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=2)

    n = snapshot_session_scores(conn, "alpha", current_iteration=2)
    assert n == 1

    row = conn.execute(
        "SELECT score, pattern FROM cr_session_scores WHERE target_path = 'src/a.py'"
    ).fetchone()
    assert row["pattern"] == "read_edit"
    # Durable raw volume has no iteration decay and no pattern multiplier.
    assert row["score"] == pytest.approx(3.0)
    assert row["score"] * PATTERN_MULTIPLIERS[row["pattern"]] == pytest.approx(6.0)


def test_snapshot_replaces_prior_rows(conn, make_session, make_interaction):
    """Re-running snapshot for the same session DELETEs old rows first."""
    make_session("alpha")
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    snapshot_session_scores(conn, "alpha", current_iteration=1)

    make_interaction(1, event="edit", target="src/a.py", iteration=2)
    snapshot_session_scores(conn, "alpha", current_iteration=2)

    rows = conn.execute(
        "SELECT pattern FROM cr_session_scores WHERE target_path = 'src/a.py'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["pattern"] == "read_edit"


def test_snapshot_retains_early_work_and_does_not_sum_repeated_turns(
    conn, make_session, make_prompt, make_interaction
):
    sess = make_session("alpha")
    early = make_prompt(sess, "early task", iteration=1)
    make_interaction(sess, context_id=early, event="edit", target="early.py", iteration=2)
    for i in range(10):
        ctx = make_prompt(sess, "late task", iteration=100 + i * 10)
        make_interaction(sess, context_id=ctx, event="edit", target="late.py", iteration=101 + i * 10)
    snapshot_session_scores(conn, "alpha", current_iteration=200)
    rows = conn.execute("SELECT target_path, score, pattern FROM cr_session_scores ORDER BY target_path").fetchall()
    assert [tuple(row) for row in rows] == [("early.py", 2.0, "edit_only"), ("late.py", 2.0, "edit_only")]


@pytest.mark.parametrize("autocommit", [False, True])
def test_snapshot_failure_restores_previous_data(
    conn, make_session, make_interaction, autocommit
):
    import sqlite3

    sess = make_session("alpha")
    make_interaction(sess, event="edit", target="old.py")
    snapshot_session_scores(conn, "alpha", 1)
    conn.commit()
    if autocommit:
        conn.isolation_level = None
    original = [tuple(row) for row in conn.execute("SELECT * FROM cr_session_scores")]
    make_interaction(sess, event="edit", target="new.py")
    conn.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON cr_session_scores "
                 "WHEN NEW.target_path = 'new.py' BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="disk failure"):
        snapshot_session_scores(conn, "alpha", 2)
    assert [tuple(row) for row in conn.execute("SELECT * FROM cr_session_scores")] == original
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_snapshot_repeated_reads_do_not_become_productive(conn, make_session, make_interaction):
    sess = make_session("alpha")
    for i in range(50):
        make_interaction(sess, event="read", target="confusing.py", iteration=i)
    snapshot_session_scores(conn, "alpha", 50)
    row = conn.execute("SELECT score, pattern FROM cr_session_scores").fetchone()
    assert tuple(row) == (1.0, "read_repeated")
