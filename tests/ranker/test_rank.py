"""End-to-end ranker pipeline: rank() entrypoint + RankResult/RankedItem."""

from __future__ import annotations

import pytest

from ken.ranker import MIN_CONFIDENCE, RankedItem, RankResult, rank
from ken.embedder import vec_to_blob


def test_rank_runs_full_pipeline(conn, make_session, make_interaction, fake_emb):
    """A clear winner on reactive should make it through the gate and out."""
    make_session("alpha")
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=1)
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    assert not result.empty
    assert any(it.target == "src/a.py" for it in result.files)


def test_rank_sorts_descending_with_alpha_tiebreak(conn, make_session, make_interaction, fake_emb):
    """Equal-score files come back in alphabetical (ascending) order."""
    make_session("alpha")
    # Two files with identical reactive patterns → identical scores.
    for path in ("src/zebra.py", "src/apple.py", "src/mango.py"):
        make_interaction(1, event="read", target=path, iteration=1)
        make_interaction(1, event="edit", target=path, iteration=1)
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    paths = [it.target for it in result.files]
    # Equal scores → ascending alpha after reverse-sort. Apple wins.
    assert paths == sorted(paths)


def test_rank_caps_top_files(conn, make_session, make_interaction, fake_emb):
    make_session("alpha")
    for i in range(15):
        make_interaction(1, event="read", target=f"src/f{i}.py", iteration=1)
        make_interaction(1, event="edit", target=f"src/f{i}.py", iteration=1)
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
        top_files=4,
    )
    assert len(result.files) == 4


def test_rank_caps_top_symbols(conn, make_session, make_file, make_symbol, fake_emb):
    make_session("alpha")
    fid = make_file("src/a.py")
    # Create many symbols that all match the query embedding.
    for i in range(10):
        make_symbol(fid, name=f"hello_{i}", qualname=f"hello_{i}", line_start=i + 1)
    # Query embeds same as a symbol name to clear the threshold.
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello_0",
        prompt_embedding=fake_emb("hello_0"),
        top_symbols=2,
    )
    assert len(result.symbols) <= 2


def test_rank_surfaces_file_for_high_scoring_symbol(conn, make_session, make_file, make_symbol, fake_emb):
    make_session("alpha")
    fid = make_file("src/ken/daemon/server.py")
    make_symbol(
        fid,
        name="CriticalEntrypoint",
        qualname="DaemonServer.CriticalEntrypoint",
        line_start=42,
    )

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="critical entrypoint",
        prompt_embedding=fake_emb("unrelated embedding text"),
    )

    assert any(it.target == "src/ken/daemon/server.py" for it in result.files)
    assert any("DaemonServer.CriticalEntrypoint" in it.target for it in result.symbols)


def test_rank_surfaces_file_for_exact_snake_case_symbol(conn, make_session, make_file, make_symbol, fake_emb):
    make_session("alpha")
    fid = make_file("mm/memory.c")
    make_symbol(fid, name="handle_mm_fault", qualname="handle_mm_fault", line_start=4323)

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="trace handle_mm_fault page fault handling",
        prompt_embedding=fake_emb("unrelated embedding text"),
    )

    assert result.files[0].target == "mm/memory.c"
    assert result.symbols[0].target == "handle_mm_fault (mm/memory.c:4323)"


def test_rank_surfaces_scheduler_core_from_exact_lowercase_symbol(
    conn, make_session, make_file, make_symbol, fake_emb
):
    make_session("alpha")
    fid = make_file("kernel/sched/core.c")
    make_symbol(fid, name="schedule", qualname="schedule", line_start=4103)
    noisy = make_file("drivers/gpu/drm/i915/gvt/scheduler.h")
    make_symbol(noisy, name="intel_gvt_schedule", qualname="intel_gvt_schedule", line_start=10)

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="look at core scheduler schedule implementation",
        prompt_embedding=fake_emb("unrelated embedding text"),
    )

    assert result.files[0].target == "kernel/sched/core.c"
    assert result.symbols[0].target == "schedule (kernel/sched/core.c:4103)"


def test_rank_includes_relevant_findings(conn, make_session, fake_emb, now_ms):
    make_session("alpha")
    conn.execute(
        """
        INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "codex wiring",
            "Use ken install . --codex to repair invalid project hooks.",
            '["codex"]',
            vec_to_blob(fake_emb("codex hook repair")),
            now_ms,
            now_ms,
        ),
    )

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="codex hook repair",
        prompt_embedding=fake_emb("codex hook repair"),
    )

    assert not result.empty
    assert result.findings[0].topic == "codex wiring"
    assert result.findings[0].tags == ["codex"]


def test_rank_surfaces_related_tests(conn, make_session, make_file, fake_emb):
    make_session("alpha")
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="src/ken/status.py",
        prompt_embedding=fake_emb("src/ken/status.py"),
    )

    assert any(it.target == "tests/test_status.py" for it in result.files)


def test_rank_surfaces_source_for_ranked_test_file(conn, make_session, make_file, fake_emb):
    make_session("alpha")
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="tests/test_status.py failing",
        prompt_embedding=fake_emb("tests/test_status.py failing"),
    )

    assert any(it.target == "src/ken/status.py" for it in result.files)


def test_rank_confidence_gate_returns_empty(conn, make_session, fake_emb):
    """No interactions, no past sessions → top_score below gate → empty."""
    make_session("alpha")
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="nothing relevant here",
        prompt_embedding=fake_emb("nothing relevant here"),
    )
    assert result.empty
    assert result.top_score == 0.0


def test_rank_includes_reasons(conn, make_session, make_interaction, fake_emb):
    make_session("alpha")
    make_interaction(1, event="read", target="src/a.py", iteration=1)
    make_interaction(1, event="edit", target="src/a.py", iteration=1)
    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
    )
    assert any("reactive" in it.reason for it in result.files)


def test_rank_drops_missing_files_when_project_root_is_known(
    tmp_path, conn, make_session, make_interaction, fake_emb
):
    make_session("alpha")
    live = tmp_path / "src" / "live.py"
    live.parent.mkdir()
    live.write_text("def live(): return 1\n")
    make_interaction(1, event="read", target="src/live.py", iteration=1)
    make_interaction(1, event="edit", target="src/live.py", iteration=1)
    make_interaction(1, event="read", target="src/stale.py", iteration=1)
    make_interaction(1, event="edit", target="src/stale.py", iteration=1)

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="hello",
        prompt_embedding=fake_emb("hello"),
        project_root=tmp_path,
    )

    assert [it.target for it in result.files] == ["src/live.py"]


def test_rank_drops_missing_symbols_when_project_root_is_known(
    tmp_path, conn, make_session, make_file, make_symbol, fake_emb
):
    make_session("alpha")
    live = tmp_path / "src" / "live.py"
    live.parent.mkdir()
    live.write_text("def live_func(): return 1\n")
    live_id = make_file("src/live.py")
    stale_id = make_file("src/stale.py")
    make_symbol(live_id, name="live_func", qualname="live_func", line_start=1)
    make_symbol(stale_id, name="stale_func", qualname="stale_func", line_start=1)

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="live_func stale_func",
        prompt_embedding=fake_emb("unrelated"),
        project_root=tmp_path,
    )

    assert [it.target for it in result.files] == ["src/live.py"]
    assert [it.target for it in result.symbols] == ["live_func (src/live.py:1)"]


def test_ranked_item_lt_score_difference():
    a = RankedItem(target="a", target_type="file", score=1.0)
    b = RankedItem(target="b", target_type="file", score=2.0)
    assert a < b
    assert not (b < a)


def test_rank_result_empty_property():
    assert RankResult().empty is True
    r = RankResult(files=[RankedItem("a", "file", 1.0)])
    assert r.empty is False
    s = RankResult(symbols=[RankedItem("S", "symbol", 1.0)])
    assert s.empty is False
    f = RankResult(findings=[])
    assert f.empty is True


def test_rank_result_top_score_max_across_files_and_symbols():
    r = RankResult(
        files=[RankedItem("a", "file", 3.0), RankedItem("b", "file", 1.0)],
        symbols=[RankedItem("S", "symbol", 4.0)],
    )
    assert r.top_score == pytest.approx(4.0)


def test_min_confidence_threshold_value():
    """Sanity: the gate is meaningful (above zero, below typical good scores)."""
    assert 0 < MIN_CONFIDENCE < 5.0
