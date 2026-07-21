"""`ken tools` — the CLI passthrough over the MCP tool registry.

The command builds its subcommands live from the same ``FastMCP`` object
``ken mcp`` serves, so these tests drive it through ``main()`` (the real
argparse path) rather than the tool functions directly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ken import _paths
from ken.cli import main
from ken.db import connect, init_schema


def _project(tmp_path: Path) -> Path:
    """A minimal indexed project: one file with one indexed symbol."""
    ken_dir = _paths.ken_dir(tmp_path)
    ken_dir.mkdir()
    _paths.meta_path(tmp_path).write_text("{}", encoding="utf-8")
    src = tmp_path / "src/parser.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("def parse_symbol():\n    return 1\n", encoding="utf-8")
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
        now_ms = int(time.time() * 1000)
        file_id = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, symbol_count) "
            "VALUES ('src/parser.py', 'python', ?, ?, ?, 1)",
            (b"\x00" * 32, int(time.time() * 1e9), now_ms),
        ).lastrowid
        conn.execute(
            "INSERT INTO ci_symbols("
            "file_id, kind, name, qualname, line_start, line_end, docstring"
            ") VALUES (?, 'function', 'parse_symbol', 'parse_symbol', 1, 2, 'Parse symbols.')",
            (file_id,),
        )
    return tmp_path


def test_tools_list_prints_every_tool(capsys, tmp_path):
    rc = main(["tools", "--path", str(tmp_path), "--list"])

    assert rc == 0
    out = capsys.readouterr().out
    # A representative spread of the registered surface.
    for name in ("ken_grep", "ken_file_symbols", "ken_blast_radius", "ken_cochange"):
        assert name in out


def test_tools_no_name_lists_tools(capsys, tmp_path):
    rc = main(["tools", "--path", str(tmp_path)])

    assert rc == 0
    assert "ken_file_symbols" in capsys.readouterr().out


def test_tools_runs_tool_and_prints_json(capsys, tmp_path):
    root = _project(tmp_path)

    rc = main(["tools", "--path", str(root), "file_symbols", "src/parser.py"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["symbols"][0]["qualname"] == "parse_symbol"
    assert payload["symbols"][0]["docstring"] == "Parse symbols."


def test_tools_accepts_ken_prefix_and_compact(capsys, tmp_path):
    root = _project(tmp_path)

    rc = main(
        ["tools", "--path", str(root), "--compact", "ken_file_symbols", "src/parser.py"]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1  # single-line JSON
    assert json.loads(out)["symbols"][0]["name"] == "parse_symbol"


def test_tools_boolean_flag_toggles_schema_default(capsys, tmp_path):
    root = _project(tmp_path)

    rc = main(
        [
            "tools",
            "--path",
            str(root),
            "file_symbols",
            "src/parser.py",
            "--no-include-docstrings",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "docstring" not in payload["symbols"][0]


def test_tools_unknown_name_reports_and_suggests(capsys, tmp_path):
    rc = main(["tools", "--path", str(tmp_path), "file_symbol"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown tool 'file_symbol'" in err
    assert "file_symbols" in err  # difflib suggestion


def test_tools_reports_missing_project(capsys, tmp_path):
    # No .ken/meta — the tool never runs.
    rc = main(["tools", "--path", str(tmp_path), "file_symbols", "src/parser.py"])

    assert rc == 1
    assert "no .ken project" in capsys.readouterr().err
