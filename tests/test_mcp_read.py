"""Default tool arguments must produce useful source, not one character."""

import json

import pytest

from ken.db import connect, init_schema
from ken.mcp import server


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / ".ken").mkdir()
    (tmp_path / ".ken/meta.json").write_text("{}")
    (tmp_path / "example.py").write_text("def useful():\n    return 42\n")
    with connect(tmp_path / ".ken/ken.db") as conn:
        init_schema(conn)
        cursor = conn.execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at) VALUES (?,?,0,0)",
            ("example.py", b"hash"),
        )
        conn.execute(
            "INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end) VALUES (?,?,?,?,?,?)",
            (cursor.lastrowid, "function", "useful", "useful", 1, 2),
        )
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    return tmp_path


def test_symbol_source_has_a_useful_default_budget(project):
    result = server.ken_read("example.py", include=["source"], qualname="useful")
    assert "return 42" in result["source"]["snippets"][0]["code"]


def test_explicit_source_budget_is_still_honored(project):
    result = server.ken_read(
        "example.py", include=["source"], qualname="useful", max_chars=8
    )
    assert len(result["source"]["snippets"][0]["code"]) == 8


def test_omitted_line_range_does_not_mean_only_first_line(project):
    result = server.ken_read("example.py", include=["source"])
    assert "return 42" in result["source"]["snippets"][0]["code"]


def test_cli_uses_same_default_source_budget(project, capsys):
    from ken.cli import main

    assert (
        main(
            [
                "tools",
                "--path",
                str(project),
                "read",
                "example.py",
                "--include",
                "source",
                "--qualname",
                "useful",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert "return 42" in result["source"]["snippets"][0]["code"]
