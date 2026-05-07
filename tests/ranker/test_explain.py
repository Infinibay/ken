"""Per-channel breakdown via ranker.explain.explain()."""

from __future__ import annotations

from ken.embedder import vec_to_blob
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
        "lexical_files",
        "lexical_symbols",
        "findings",
    }
    assert set(out["channels"]) == expected
    assert "merge_before_boosts" in out
    assert set(out["boosts"]) == {
        "symbol_file_affinity",
        "freshness",
        "cooc",
        "test_affinity",
        "import_affinity",
        "dismissal",
    }
    assert "final_files" in out
    assert "final_symbols" in out
    assert "final_findings" in out


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


def test_explain_includes_finding_channel(conn, make_session, fake_emb, now_ms):
    make_session("alpha")
    conn.execute(
        """
        INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "codex wiring",
            "Use --codex to repair hooks.",
            '["codex"]',
            vec_to_blob(fake_emb("codex hook repair")),
            now_ms,
            now_ms,
        ),
    )

    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="codex hook repair",
        prompt_embedding=fake_emb("codex hook repair"),
    )

    assert out["channels"]["findings"][0]["topic"] == "codex wiring"
    assert out["final_findings"][0]["tags"] == ["codex"]


def test_explain_includes_test_affinity_diff(conn, make_session, make_file, fake_emb):
    make_session("alpha")
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="src/ken/status.py",
        prompt_embedding=fake_emb("src/ken/status.py"),
    )

    assert any(
        d["target"] == "tests/test_status.py"
        for d in out["boosts"]["test_affinity"]
    )


def test_explain_includes_symbol_file_affinity_diff(
    conn, make_session, make_file, make_symbol, fake_emb
):
    make_session("alpha")
    fid = make_file("src/ken/daemon/server.py")
    make_symbol(
        fid,
        name="CriticalEntrypoint",
        qualname="DaemonServer.CriticalEntrypoint",
        line_start=42,
    )

    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="critical entrypoint",
        prompt_embedding=fake_emb("unrelated embedding text"),
    )

    assert any(
        d["target"] == "src/ken/daemon/server.py"
        for d in out["boosts"]["symbol_file_affinity"]
    )


def test_explain_includes_import_affinity_diff(conn, make_session, make_file, fake_emb):
    make_session("alpha")
    src_id = make_file("src/app.py")
    util_id = make_file("src/util.py")
    conn.execute(
        "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) VALUES (?, 'src.util', ?, 1)",
        (src_id, util_id),
    )

    out = explain(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="src/app.py",
        prompt_embedding=fake_emb("src/app.py"),
    )

    assert any(d["target"] == "src/util.py" for d in out["boosts"]["import_affinity"])


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
