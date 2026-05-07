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
from ken.search import search_files, search_symbols


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
            src.write_text("def indexed():\n    return 1\n", encoding="utf-8")
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
            ) VALUES (?, 'function', 'parse_symbol', 'parse_symbol', 7, 9, 'Parse symbols.', ?)
            """,
            (parser_id, vec_to_blob(np.array([1.0, 0.0], dtype=np.float32))),
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
