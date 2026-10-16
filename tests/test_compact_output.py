"""Public presentation contracts, independent of ranking implementation."""
import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from ken.db import connect, init_schema
from ken.mcp import server


def test_numbered_disjoint_code_preserves_whitespace_and_warning():
    from ken.presentation import render_compact
    value = {"path": "a.py", "snippets": [
        {"label": "A.go", "line": 12, "line_end": 13, "code": "    x()\n    y()"},
        {"label": "A.go", "line": 42, "line_end": 42, "code": "    return x"}],
        "warnings": ["Index may be stale; reindex."], "complete": False}
    before = copy.deepcopy(value)
    text = render_compact(value)
    assert "a.py:12-13 :: A.go" in text
    assert "12 |     x()\n13 |     y()" in text
    assert "a.py:42-42 :: A.go" in text
    assert "42 |     return x" in text
    assert "complete: false" in text and "Index may be stale" in text
    assert value == before
    assert len(text) < len(json.dumps(value))


def test_ranges_do_not_claim_unshown_lines_and_fts_has_no_fake_line():
    from ken.presentation import render_compact
    text = render_compact({"path": "a.py", "line": 3, "line_end": 80, "code": "hello\nworld"})
    assert "a.py:3-4" in text and "partial" in text
    assert "a.py:3-80" not in text
    assert "3 | hello\n4 | world" in text
    fts = render_compact({"results": [{"path": "b.py", "snippet": "[some] … excerpt"}]})
    assert "[some] … excerpt" in fts and "1 |" not in fts


def test_errors_empty_and_diagnostics_are_explicit():
    from ken.presentation import render_compact
    assert render_compact([]) == "No results."
    assert "results: none" in render_compact({"results": [], "complete": True})
    text = render_compact({"ok": False, "error": "Missing index", "next_action": "Run ken index"})
    assert "Missing index" in text and "Run ken index" in text
    value = [{"path": "a.py", "line": 7, "qualname": "run", "score": .125,
              "source_hash": "f" * 64, "docstring": "Run the job."}]
    assert "score" not in render_compact(value) and "f" * 64 not in render_compact(value)
    assert "score" in render_compact(value, diagnostics=True)


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / ".ken").mkdir()
    (tmp_path / ".ken/meta.json").write_text("{}")
    (tmp_path / "a.py").write_text("def run():\n    return 42\n")
    with connect(tmp_path / ".ken/ken.db") as conn:
        init_schema(conn)
        cur = conn.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at) VALUES ('a.py',?,0,0)", (b"hash",))
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end) VALUES (?,'function','run','run',1,2)", (cur.lastrowid,))
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    return tmp_path


def test_all_transport_schemas_offer_compact_and_native_json():
    for tool in server.list_tools():
        prop = tool.parameters["properties"]["output_format"]
        assert prop == {"type": "string", "enum": ["compact", "json"], "default": "compact"}
        assert "output_format" not in tool.parameters.get("required", [])


def test_transport_does_not_change_internal_python_contract(project):
    native = server.ken_read("a.py", include=["source"], qualname="run")
    tool = next(t for t in server.list_tools() if t.name == "ken_read")
    assert isinstance(native, dict)
    assert tool.fn("a.py", include=["source"], qualname="run", output_format="json") == native
    text = tool.fn("a.py", include=["source"], qualname="run")
    assert "a.py:1-2 :: run" in text and "2 |     return 42" in text
    with pytest.raises(ValueError, match="output_format"):
        tool.fn("a.py", output_format="yaml")


def test_default_tools_cli_is_text_and_json_is_opt_in(project, capsys):
    from ken.cli import main
    argv = ["tools", "--path", str(project), "read", "a.py", "--include", "source", "--qualname", "run"]
    assert main(argv) == 0
    text = capsys.readouterr().out
    assert "2 |     return 42" in text
    assert not text.startswith('{')
    assert main([*argv, "--output-format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["source"]["snippets"][0]["code"].startswith("1: def run")


def test_real_mcp_default_text_and_explicit_json(project):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "ken", "mcp", str(project)],
                                       env={"PYTHONPATH": str(Path(server.__file__).resolve().parents[2])})
        with (project / "mcp.log").open("w") as log:
            async with stdio_client(params, errlog=log) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    for tool in listing.tools:
                        assert tool.input_schema["properties"]["output_format"]["default"] == "compact"
                    args = {"path": "a.py", "include": ["source"], "qualname": "run"}
                    result = await session.call_tool("ken_read", args)
                    assert not result.is_error and len(result.content) == 1
                    assert "2 |     return 42" in result.content[0].text
                    assert not result.structured_content
                    raw = await session.call_tool("ken_read", args | {"output_format": "json"})
                    assert not raw.is_error
                    assert json.loads(raw.content[0].text)["ok"] is True
    asyncio.run(exercise())


def test_search_preview_keeps_rank_and_does_not_read_outside_project(project):
    from ken.presentation import search_previews, render_compact
    hits = [{"file": "a.py", "line": 1, "line_end": 2, "qualname": "run", "score": .8},
            {"file": "../outside.py", "line": 1, "qualname": "escape", "score": .7}]
    before = copy.deepcopy(hits)
    result = search_previews(hits, project)
    assert [r["file"] for r in result] == ["a.py", "../outside.py"]
    assert "2 |     return 42" in render_compact(result)
    assert "preview_unavailable" in render_compact(result)
    assert hits == before


def test_find_default_presentation_does_not_require_new_retrieval_index(project, capsys):
    from ken.cli import main
    assert main(["tools", "--path", str(project), "find", "run", "--scope", "symbols"]) == 0
    text = capsys.readouterr().out
    assert "a.py:1-2" in text and "return 42" in text
    assert "ranking_score" not in text and "retrieval_index_required" not in text


def test_direct_search_default_is_compact_and_json_preserves_native(project, capsys):
    from ken.cli import main
    assert main(["search-symbols", "run", "--path", str(project)]) == 0
    text = capsys.readouterr().out
    assert "a.py:1-2 :: run" in text and "2 |     return 42" in text
    assert "score" not in text
    assert main(["search-symbols", "run", "--path", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["qualname"] == "run"


def test_analysis_cli_defaults_are_text_with_json_opt_in(capsys):
    from ken.cli import main
    for args in (["kql2", "--capabilities"], ["structural", "catalog"]):
        assert main(args) == 0
        text = capsys.readouterr().out
        assert text.strip() and not text.lstrip().startswith("{")
        assert main([*args, "--json"]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_query_table_keeps_column_binding_row_boundaries_and_unknowns():
    from ken.presentation import render_compact
    text = render_compact({"columns": ["owner", "consumer"],
        "rows": [["Alpha", "One"], ["Beta", "Two"]], "complete": False, "status": None})
    assert "row 1" in text and "row 2" in text
    assert "owner: Alpha" in text and "consumer: One" in text
    assert text.index("consumer: One") < text.index("owner: Beta")
    assert "complete: false" in text and "status: none" in text


def test_responsibility_compact_keeps_candidates_caveats_and_partial_verification():
    from ken.presentation import render_compact
    value = {"status": "candidates", "score_kind": "not_probability", "candidates": [
        {"path": "a.py", "line": 4, "symbol": "Reader", "evidence": "Read values.",
         "counterevidence": ["Does not write values."], "assumptions": ["Documentation may be wrong."],
         "structure": {"calls": {"sites": [{"name": "irrelevant_trace_detail"}],
             "coverage_complete": False, "unknown_candidates": 3, "reason": "budget"}}}],
        "responsibility_map": {"nodes": [{"id": 99}], "complete": False}}
    before = copy.deepcopy(value)
    text = render_compact(value, tool_name="ken_who")
    assert "Reader" in text and "Read values." in text
    assert "Does not write" in text and "may be wrong" in text
    assert "coverage_complete=false" in text and "unknown_candidates=3" in text and "reason=budget" in text
    assert "irrelevant_trace_detail" not in text and "responsibility_map" not in text
    assert value == before
    assert "irrelevant_trace_detail" in render_compact(value, tool_name="ken_who", diagnostics=True)


def test_reasoning_compact_keeps_binding_sources_and_unfinished_search():
    from ken.presentation import render_compact
    value = {"status": "supported", "answers": [{"binding": {"?answer": "Reader"},
             "fact": {"predicate": "reads", "subject": "Reader", "object": "settings"},
             "proof": {"deep_trace": "noise", "support": {"source": "doc-1"}}}],
        "metrics": {"complete": False, "resumable": True, "pending": 3, "total_work": 999},
        "sources": {"doc-1": "reader.py docstring"}, "semantics": "Conditional on supplied premises."}
    text = render_compact(value, tool_name="ken_reason")
    assert "?answer: Reader" in text and "reader.py docstring" in text and "Conditional" in text
    assert "complete: false" in text and "resumable: true" in text and "pending: 3" in text
    assert "deep_trace" not in text and "total_work" not in text
    assert "deep_trace" in render_compact(value, tool_name="ken_reason", diagnostics=True)


def test_number_like_source_is_not_mistaken_for_a_legacy_line_prefix():
    from ken.presentation import render_compact
    raw = {"path": "config.yaml", "line": 1, "line_end": 1, "code": "1: keep this value"}
    assert "1 | 1: keep this value" in render_compact(raw)
    legacy = raw | {"code": "1: 1: keep this value"}
    assert "1 | 1: keep this value" in render_compact(legacy, tool_name="ken_read")


def test_trailing_empty_source_line_keeps_its_number():
    from ken.presentation import render_compact
    text = render_compact({"path": "a.py", "start_line": 8, "end_line": 9, "content": "run()\n"})
    assert "a.py:8-9" in text and "8 | run()\n9 | " in text
    assert "partial" not in text
