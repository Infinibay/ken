"""End-to-end ranker pipeline: rank() entrypoint + RankResult/RankedItem."""

from __future__ import annotations

import pytest

from ken.ranker import MIN_CONFIDENCE, RankedItem, RankResult, _drop_missing_paths, rank
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


def test_rank_uses_doc_intent_channel(conn, make_session, make_file, fake_emb, now_ms):
    make_session("alpha")
    fid = make_file("src/ken/daemon/index_queue.py")
    conn.execute(
        "INSERT INTO ci_intent_sources(file_id, source_kind, text, embedding, weight, updated_at) "
        "VALUES (?, 'module_docstring', 'Background re-index queue for filesystem changes.', ?, 1.0, ?)",
        (
            fid,
            vec_to_blob(fake_emb("Background re-index queue for filesystem changes.")),
            now_ms,
        ),
    )

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="filesystem change queue",
        prompt_embedding=fake_emb("Background re-index queue for filesystem changes."),
    )

    assert result.files[0].target == "src/ken/daemon/index_queue.py"
    assert "doc-intent:module_docstring" in result.files[0].reason


def test_rank_manual_spanish_parser_query_uses_lexical_aliases(
    conn, make_session, make_file, make_symbol, make_interaction, fake_emb
):
    session_id = make_session("alpha")
    make_interaction(session_id, event="cited", target="src/ken/status.py", iteration=1)
    parser_file = make_file("src/ken/parsers/types.py")
    make_symbol(
        parser_file,
        name="ParsedFile",
        qualname="ParsedFile",
        kind="class",
        line_start=25,
        line_end=30,
    )

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="Que clase se encarga de parsear el codigo de un fichero?",
        prompt_embedding=fake_emb("unrelated"),
        include_reactive=False,
    )

    assert result.symbols[0].target == "ParsedFile (src/ken/parsers/types.py:25)"
    assert result.files[0].target == "src/ken/parsers/types.py"


def test_rank_ignores_project_name_as_lexical_path_signal(
    tmp_path, conn, make_file
):
    from ken.ranker.channels import lexical_scores

    root = tmp_path / "ken"
    root.mkdir()
    make_file("src/ken/install.py")
    make_file("install.sh")

    files, _symbols = lexical_scores(
        conn,
        prompt="install ken from a local checkout",
        project_root=root,
    )

    assert {item.target for item in files} == {"src/ken/install.py", "install.sh"}
    assert all("ken" not in item.reason for item in files)


def test_rank_uses_exact_literal_tokens_for_tool_contracts(
    tmp_path, conn, make_session, make_file, fake_emb
):
    root = tmp_path / "project"
    root.mkdir()
    src = root / "src/ken/daemon"
    src.mkdir(parents=True)
    (src / "server.py").write_text(
        "def classify():\n"
        "    return {'exec_command': 'read', 'apply_patch': 'edit'}\n",
        encoding="utf-8",
    )
    (root / "src/ken/daemon/index_queue.py").write_text(
        "def apply():\n    return None\n",
        encoding="utf-8",
    )
    make_session("alpha")
    make_file("src/ken/daemon/server.py")
    make_file("src/ken/daemon/index_queue.py")

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="why are exec_command and apply_patch not recorded",
        prompt_embedding=fake_emb("unrelated"),
        project_root=root,
    )

    assert result.files[0].target == "src/ken/daemon/server.py"
    assert "literal:apply_patch,exec_command" in result.files[0].reason


def test_rank_matches_spaced_prompt_to_underscored_literals(
    tmp_path, conn, make_session, make_file, fake_emb
):
    root = tmp_path / "project"
    root.mkdir()
    pkg = root / "src/ken/ranker"
    pkg.mkdir(parents=True)
    (pkg / "output.py").write_text(
        "def render_block(result, *, max_chars=None):\n"
        "    return _fit_block(result, max_chars=max_chars)\n",
        encoding="utf-8",
    )
    make_session("alpha")
    make_file("src/ken/ranker/output.py")

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="inspect ranked context stats and max chars",
        prompt_embedding=fake_emb("unrelated"),
        project_root=root,
    )

    assert result.files[0].target == "src/ken/ranker/output.py"
    assert "literal:max_chars" in result.files[0].reason


def test_rank_does_not_literalize_arbitrary_natural_bigrams(
    tmp_path, conn, make_session, make_file, fake_emb
):
    root = tmp_path / "project"
    root.mkdir()
    parser_dir = root / "tests/parsers"
    parser_dir.mkdir(parents=True)
    (parser_dir / "test_c.py").write_text(
        "def test_parser_extracts_symbols():\n    pass\n",
        encoding="utf-8",
    )
    make_session("alpha")
    make_file("tests/parsers/test_c.py")

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="parser extracts TypeScript class methods",
        prompt_embedding=fake_emb("unrelated"),
        project_root=root,
    )

    assert all("literal:parser_extracts" not in item.reason for item in result.files)


def test_rank_does_not_give_exact_bonus_to_generic_file_helpers(conn, make_file):
    from ken.ranker.channels import lexical_scores

    make_file("tests/test_helpers.py")
    conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, docstring) "
        "VALUES ((SELECT id FROM ci_files WHERE path = 'tests/test_helpers.py'), "
        "'function', '_file', '_file', 10, 11, NULL)"
    )

    _files, symbols = lexical_scores(conn, "show file symbols snippets")

    helper = next(item for item in symbols if item.target.startswith("_file "))
    assert "+exact" not in helper.reason


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


def test_rank_drops_missing_symbols_with_parenthesized_qualname(
    tmp_path, conn, make_session, make_file, make_symbol, fake_emb
):
    make_session("alpha")
    live = tmp_path / "static" / "chunk.js"
    live.parent.mkdir()
    live.write_text("export const iterator = Symbol.asyncIterator;\n")
    live_id = make_file("static/chunk.js")
    make_symbol(
        live_id,
        name="Symbol.asyncIterator",
        qualname="stream[Symbol.asyncIterator)]",
        line_start=1,
    )

    result = rank(
        conn,
        agent_id="alpha",
        current_iteration=1,
        prompt="async iterator stream",
        prompt_embedding=fake_emb("Symbol.asyncIterator"),
        project_root=tmp_path,
    )

    assert result.symbols[0].target == "stream[Symbol.asyncIterator)] (static/chunk.js:1)"


def test_drop_missing_paths_filters_invalid_long_paths(tmp_path):
    live = tmp_path / "src" / "live.py"
    live.parent.mkdir()
    live.write_text("x = 1\n")
    too_long = "x" * 5000 + ".py"

    files, symbols = _drop_missing_paths(
        tmp_path,
        [
            RankedItem("src/live.py", "file", 2.0),
            RankedItem(too_long, "file", 2.0),
        ],
        [
            RankedItem("live (src/live.py:1)", "symbol", 2.0),
            RankedItem(f"bad ({too_long}:1)", "symbol", 2.0),
        ],
    )

    assert [it.target for it in files] == ["src/live.py"]
    assert [it.target for it in symbols] == ["live (src/live.py:1)"]


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
