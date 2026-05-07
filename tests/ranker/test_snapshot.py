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
    # Raw stored = (read+edit raw with decay) — what reactive computed
    # before the pattern multiplier. Check it's NOT the post-mult value.
    mult = PATTERN_MULTIPLIERS["read_edit"]
    # The exact raw value is iter-decay-dependent; just assert that
    # post-mult-stored vs raw-stored is reconcilable: stored * mult
    # should equal what reactive_scores would produce as `final`.
    from ken.ranker.channels import reactive_scores
    items = reactive_scores(conn, "alpha", current_iteration=2)
    assert items[0].score == pytest.approx(row["score"] * mult)


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
