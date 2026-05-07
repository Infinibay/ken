"""Daemon helpers that don't need the HTTP layer: cited-paths extraction."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ken.daemon.server import _classify_tool, _extract_cited_paths
from ken.db import init_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


def _index_file(conn, path: str) -> None:
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at) VALUES (?, ?, ?, ?)",
        (path, b"\x00" * 32, 0, 0),
    )


def test_extract_full_path_match(conn):
    _index_file(conn, "src/auth.py")
    text = "I edited src/auth.py to fix the bug."
    assert _extract_cited_paths(conn, text) == ["src/auth.py"]


def test_extract_dedupes_repeated_mentions(conn):
    _index_file(conn, "src/auth.py")
    text = "src/auth.py and src/auth.py and again src/auth.py."
    assert _extract_cited_paths(conn, text) == ["src/auth.py"]


def test_extract_bare_filename_resolves_when_unique(conn):
    _index_file(conn, "src/deep/nested/module.py")
    text = "Look at module.py for details."
    assert _extract_cited_paths(conn, text) == ["src/deep/nested/module.py"]


def test_extract_bare_filename_skipped_when_ambiguous(conn):
    """If multiple ci_files end with the bare name, we skip — too risky."""
    _index_file(conn, "src/a/util.py")
    _index_file(conn, "src/b/util.py")
    text = "Check util.py somewhere."
    assert _extract_cited_paths(conn, text) == []


def test_extract_filters_unknown_extension(conn):
    _index_file(conn, "src/auth.py")
    text = "binary blob.exe and config.bin should not match"
    assert _extract_cited_paths(conn, text) == []


def test_extract_filters_unindexed_files(conn):
    """Path-shaped tokens that don't exist in ci_files don't make it through."""
    _index_file(conn, "src/auth.py")
    text = "ghost/file.py is mentioned but not indexed."
    assert _extract_cited_paths(conn, text) == []


def test_extract_handles_path_with_line_number(conn):
    _index_file(conn, "src/auth.py")
    text = "the bug is at src/auth.py:42 in login()"
    assert _extract_cited_paths(conn, text) == ["src/auth.py"]


def test_extract_empty_input(conn):
    assert _extract_cited_paths(conn, "") == []
    assert _extract_cited_paths(conn, "no paths here") == []


def test_classify_codex_function_tools():
    assert _classify_tool("functions.apply_patch", {"file_path": "src/a.py"}) == (
        "edit",
        "src/a.py",
    )
    assert _classify_tool(
        "functions.exec_command",
        {"cmd": "sed -n '1,80p' src/ken/status.py", "workdir": "."},
    ) == ("read", "src/ken/status.py")
    assert _classify_tool("functions.apply_patch", "raw patch text") == ("edit", None)


def test_classify_extracts_patch_paths_from_text():
    patch = "*** Begin Patch\n*** Update File: src/ken/status.py\n@@\n"
    assert _classify_tool("functions.apply_patch", patch) == ("edit", "src/ken/status.py")


def test_classify_exec_command_falls_back_to_workdir():
    assert _classify_tool("functions.exec_command", {"cmd": "uv run pytest", "workdir": "."}) == (
        "read",
        ".",
    )
