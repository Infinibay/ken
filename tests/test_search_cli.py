"""Direct semantic search helpers and CLI commands."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ken import _paths
from ken.cli import main
from ken.db import connect, init_schema
from ken.embedder import vec_to_blob
from ken.memory import recall, remember
from ken.search import (
    changed_context,
    file_neighbors,
    file_outline,
    file_snippets,
    file_symbols,
    find_tests,
    module_graph,
    project_overview,
    search_files,
    search_symbols,
    symbol_detail,
)


class FakeEmbedder:
    def embed_query(self, text: str) -> np.ndarray:
        if "symbol" in text or "parser" in text:
            return np.array([1.0, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0], dtype=np.float32)


def _project(tmp_path: Path) -> Path:
    ken_dir = _paths.ken_dir(tmp_path)
    ken_dir.mkdir()
    _paths.meta_path(tmp_path).write_text("{}", encoding="utf-8")
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
        now_ms = int(time.time() * 1000)
        for path, emb in [
            ("src/parser.py", np.array([1.0, 0.0], dtype=np.float32)),
            ("src/status.py", np.array([0.0, 1.0], dtype=np.float32)),
        ]:
            src = tmp_path / path
            src.parent.mkdir(parents=True, exist_ok=True)
            if path == "src/parser.py":
                src.write_text(
                    "from src.status import report\n\n"
                    "def parse_symbol():\n"
                    "    return report()\n",
                    encoding="utf-8",
                )
            else:
                src.write_text("def report():\n    return 1\n", encoding="utf-8")
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
                "VALUES (?, 'python', ?, ?, ?, ?)",
                (path, b"\x00" * 32, int(time.time() * 1e9), now_ms, vec_to_blob(emb)),
            )
        parser_id = conn.execute(
            "SELECT id FROM ci_files WHERE path = 'src/parser.py'"
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO ci_symbols(
                file_id, kind, name, qualname, line_start, line_end, docstring, embedding
            ) VALUES (?, 'function', 'parse_symbol', 'parse_symbol', 3, 4, 'Parse symbols.', ?)
            """,
            (parser_id, vec_to_blob(np.array([1.0, 0.0], dtype=np.float32))),
        )
        conn.execute(
            "UPDATE ci_files SET symbol_count = 1 WHERE id = ?",
            (parser_id,),
        )
        status_id = conn.execute(
            "SELECT id FROM ci_files WHERE path = 'src/status.py'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) "
            "VALUES (?, 'src.status', ?, 1)",
            (parser_id, status_id),
        )
        test_path = "tests/test_parser.py"
        test_src = tmp_path / test_path
        test_src.parent.mkdir(parents=True, exist_ok=True)
        test_src.write_text("from src.parser import parse_symbol\n", encoding="utf-8")
        test_id = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
            "VALUES (?, 'python', ?, ?, ?)",
            (test_path, b"\x01" * 32, int(time.time() * 1e9), now_ms),
        ).lastrowid
        conn.execute(
            "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) "
            "VALUES (?, 'src.parser', ?, 1)",
            (test_id, parser_id),
        )
    return tmp_path


def test_search_files_orders_by_similarity(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        hits = search_files(conn, "parser", limit=2)

    assert [h["path"] for h in hits] == ["src/parser.py", "src/status.py"]
    assert hits[0]["symbols"][0]["name"] == "parse_symbol"


def test_search_files_filters_missing_paths_when_project_root_is_known(monkeypatch, tmp_path):
    root = _project(tmp_path)
    (root / "src/parser.py").unlink()
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        hits = search_files(conn, "parser", limit=2, project_root=root)

    assert [h["path"] for h in hits] == ["src/status.py"]


def test_search_symbols_orders_by_similarity(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        hits = search_symbols(conn, "symbol lookup", limit=5)

    assert len(hits) == 1
    assert hits[0]["file"] == "src/parser.py"
    assert hits[0]["qualname"] == "parse_symbol"


def test_search_symbols_filters_missing_paths_when_project_root_is_known(monkeypatch, tmp_path):
    root = _project(tmp_path)
    (root / "src/parser.py").unlink()
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        hits = search_symbols(conn, "symbol lookup", limit=5, project_root=root)

    assert hits == []


def test_file_symbols_returns_indexed_outline(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_symbols(conn, "src/parser.py", project_root=root)

    assert out == {
        "ok": True,
        "path": "src/parser.py",
        "language": "python",
        "symbols": [
            {
                "kind": "function",
                "name": "parse_symbol",
                "qualname": "parse_symbol",
                "line": 3,
                "line_end": 4,
                "docstring": "Parse symbols.",
            }
        ],
    }


def test_file_symbols_can_omit_docstrings(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_symbols(conn, "./src/parser.py", include_docstrings=False)

    assert out["symbols"] == [
        {
            "kind": "function",
            "name": "parse_symbol",
            "qualname": "parse_symbol",
            "line": 3,
            "line_end": 4,
        }
    ]


def test_file_symbols_reports_missing_file(tmp_path):
    root = _project(tmp_path)
    (root / "src/parser.py").unlink()

    with connect(_paths.db_path(root)) as conn:
        out = file_symbols(conn, "src/parser.py", project_root=root)

    assert out == {"ok": False, "error": "file missing on disk", "path": "src/parser.py"}


def test_file_symbols_reports_unindexed_file(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_symbols(conn, "src/unknown.py", project_root=root)

    assert out == {"ok": False, "error": "file not indexed", "path": "src/unknown.py"}


def test_file_outline_includes_symbols_and_imports(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_outline(conn, "src/parser.py", project_root=root)

    assert out["path"] == "src/parser.py"
    assert out["symbol_count"] == 1
    assert out["symbols"][0]["qualname"] == "parse_symbol"
    assert out["imports"] == [
        {"module": "src.status", "path": "src/status.py", "line": 1, "internal": True}
    ]
    assert out["imported_by"][0]["path"] == "tests/test_parser.py"


def test_file_neighbors_returns_imports_importers_and_tests(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_neighbors(conn, "src/parser.py", project_root=root)

    assert out["imports"][0]["path"] == "src/status.py"
    assert out["imported_by"][0]["path"] == "tests/test_parser.py"
    assert out["tests"][0]["path"] == "tests/test_parser.py"
    assert "src/status.py" in out["neighbors"]


def test_symbol_detail_can_include_snippet(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = symbol_detail(
            conn,
            "src/parser.py",
            "parse_symbol",
            include_snippet=True,
            project_root=root,
        )

    assert out["symbol"]["docstring"] == "Parse symbols."
    assert "3: def parse_symbol():" in out["snippet"]


def test_module_graph_returns_bounded_import_edges(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = module_graph(conn, "src/parser.py", depth=1, project_root=root)

    assert {"path": "src/parser.py", "language": "python", "symbol_count": 1} in out["nodes"]
    assert {"kind": "import", "from": "src/parser.py", "to": "src/status.py", "line": 1} in out["edges"]


def test_find_tests_returns_likely_test_files(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = find_tests(conn, "src/parser.py", project_root=root)

    assert out["tests"][0] == {"path": "tests/test_parser.py", "reason": "imports target"}


def test_file_snippets_returns_requested_symbol_source(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = file_snippets(conn, "src/parser.py", symbols=["parse_symbol"], project_root=root)

    assert out["snippets"][0]["label"] == "parse_symbol"
    assert "4:     return report()" in out["snippets"][0]["code"]


def test_project_overview_summarizes_index(tmp_path):
    root = _project(tmp_path)

    with connect(_paths.db_path(root)) as conn:
        out = project_overview(conn)

    assert out["files"] == 3
    assert out["languages"] == {"python": 3}
    assert {"path": "src", "files": 2} in out["top_dirs"]


def test_changed_context_enriches_git_status(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr(
        "ken.search._git_status",
        lambda project_root: [{"status": " M", "path": "src/parser.py"}],
    )

    with connect(_paths.db_path(root)) as conn:
        out = changed_context(conn, root)

    assert out["changed"][0]["indexed"] is True
    assert out["changed"][0]["symbols"][0]["name"] == "parse_symbol"
    assert out["changed"][0]["tests"][0]["path"] == "tests/test_parser.py"


def test_search_files_cli_prints_hits(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    rc = main(["search-files", "--path", str(root), "parser"])

    assert rc == 0
    assert "src/parser.py" in capsys.readouterr().out


def test_search_symbols_cli_prints_json(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: FakeEmbedder())

    rc = main(["search-symbols", "--path", str(root), "--json", "symbol"])

    assert rc == 0
    assert '"qualname": "parse_symbol"' in capsys.readouterr().out


def test_search_cli_reports_missing_project(capsys, tmp_path):
    rc = main(["search-files", "--path", str(tmp_path), "parser"])

    assert rc == 1
    assert "no .ken project" in capsys.readouterr().err


def test_remember_and_recall_helpers(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        out = remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])
        hits = recall(conn, "codex symbol", limit=3)

    assert out == {"ok": True, "topic": "codex wiring"}
    assert hits[0]["topic"] == "codex wiring"
    assert hits[0]["tags"] == ["codex"]


def test_remember_cli_prints_confirmation(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    rc = main(
        [
            "remember",
            "--path",
            str(root),
            "--tag",
            "codex",
            "codex wiring",
            "Use --codex to repair hooks.",
        ]
    )

    assert rc == 0
    assert "remembered: codex wiring" in capsys.readouterr().out


def test_recall_cli_prints_json(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())
    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])

    rc = main(["recall", "--path", str(root), "--json", "codex"])

    assert rc == 0
    assert '"topic": "codex wiring"' in capsys.readouterr().out
