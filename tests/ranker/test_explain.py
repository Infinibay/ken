"""Per-channel breakdown via ranker.explain.explain()."""

from __future__ import annotations

from ken.ranker.explain import _diff, explain


def test_explain_returns_all_channel_keys(conn, make_session, fake_emb):
    make_session("alpha")
    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    assert "channels" in out
    expected = {
        "explicit_files",
        "explicit_symbols",
        "reactive",
        "predictive",
        "fuzzy_files",
        "fuzzy_symbols",
    }
    assert set(out["channels"]) == expected
    assert "merge_before_boosts" in out
    assert set(out["boosts"]) == {"freshness", "cooc", "dismissal"}
    assert "final_files" in out
    assert "final_symbols" in out


def test_explain_pre_boost_snapshot_matches_merge(conn, make_session, make_interaction, fake_emb):
    """merge_before_boosts captures the merged scores in order before any boost runs."""
    make_session("alpha")
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=1)
    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    # No db files row for src/a.py → no freshness; no past sessions → no cooc/dismiss.
    pre = {row["target"]: row["score"] for row in out["merge_before_boosts"]}
    assert "src/a.py" in pre


def test_explain_freshness_diff_records_change(conn, make_session, make_interaction, make_file, fake_emb):
    make_session("alpha")
    make_file("src/a.py", days_old=0.0)  # freshness applies
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=1)
    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    fresh_diffs = out["boosts"]["freshness"]
    assert any(d["target"] == "src/a.py" and d["delta"] > 0 for d in fresh_diffs)


def test_diff_skips_unchanged():
    before = {"a": 1.0, "b": 2.0}
    after = {"a": 1.0, "b": 3.0}
    diffs = _diff(before, after)
    targets = {d["target"] for d in diffs}
    assert targets == {"b"}
    assert diffs[0]["delta"] == 1.0


def test_diff_handles_creation_and_removal():
    before = {"a": 1.0}
    after = {"b": 2.0}
    diffs = _diff(before, after)
    by_target = {d["target"]: d for d in diffs}
    assert by_target["a"]["after"] is None
    assert by_target["b"]["before"] is None
