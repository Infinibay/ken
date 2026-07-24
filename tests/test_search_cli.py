"""Direct semantic search helpers and CLI commands."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ken import _paths
from ken.cli import main
from ken.db import connect, init_schema
from ken.embedder import vec_to_blob
from ken.memory import forget, format_recall_hits, list_findings, recall, remember
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
    """Implements the full Embedder protocol.

    Stored documents go through ``embed_passages`` and queries through
    ``embed_query``; a double that only offers one of them would let a
    query/passage mix-up pass unnoticed.
    """

    def _vec(self, text: str) -> np.ndarray:
        if "symbol" in text or "parser" in text:
            return np.array([1.0, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0], dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


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

    top = out["tests"][0]
    assert top["path"] == "tests/test_parser.py"
    # Both channels fire and both are kept — neither overwrites the other.
    assert top["reason"] == "imports target; named for target"
    assert top["score"] == 4.0  # imports (1.0) + named by convention (3.0)


class _UnitQueryEmbedder:
    """Query vector is always [1, 0], so a row's cosine is its first component."""

    def embed_passages(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]

    def embed_queries(self, texts):
        return [np.array([1.0, 0.0], dtype=np.float32) for _ in texts]

    def embed_query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


def _add_symbol(conn, file_id, name, vec):
    conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, "
        "docstring, embedding) VALUES (?, 'function', ?, ?, 1, 2, '', ?)",
        (file_id, name, name, vec_to_blob(np.array(vec, dtype=np.float32))),
    )


def test_search_symbols_puts_an_exact_name_match_first(monkeypatch, tmp_path):
    # A bare identifier embeds about as close to a long test name as to the
    # symbol itself, and the longer name often wins on cosine alone.
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: _UnitQueryEmbedder())
    with connect(_paths.db_path(root)) as conn:
        parser_id = conn.execute(
            "SELECT id FROM ci_files WHERE path = 'src/parser.py'"
        ).fetchone()["id"]
        _add_symbol(conn, parser_id, "blast_radius", [0.80, 0.60])
        _add_symbol(conn, parser_id, "test_blast_radius_reverse", [0.90, 0.436])

        hits = search_symbols(conn, "blast_radius", limit=3, project_root=root)

    assert hits[0]["qualname"] == "blast_radius"
    assert hits[0]["match"] == "exact"
    # Ordering is by fused evidence, not by cosine — the runner-up scores higher.
    assert hits[1]["score"] > hits[0]["score"]
    assert hits[1]["match"] == "tokens"


def test_search_symbols_leaves_prose_queries_on_pure_similarity(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.search.get_embedder", lambda: _UnitQueryEmbedder())
    with connect(_paths.db_path(root)) as conn:
        parser_id = conn.execute(
            "SELECT id FROM ci_files WHERE path = 'src/parser.py'"
        ).fetchone()["id"]
        _add_symbol(conn, parser_id, "blast_radius", [0.80, 0.60])
        _add_symbol(conn, parser_id, "test_blast_radius_reverse", [0.90, 0.436])

        hits = search_symbols(conn, "which files does an edit affect", limit=3,
                              project_root=root)

    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all("match" not in h for h in hits)


def test_find_tests_ranks_the_conventionally_named_test_first(tmp_path):
    # A widely-imported module is imported by nearly every test; without
    # ranking, the one test actually named after it lands wherever insertion
    # order put it.
    root = _project(tmp_path)
    with connect(_paths.db_path(root)) as conn:
        now_ms = int(time.time() * 1000)
        for path in ("tests/test_helpers.py", "tests/test_parser.py", "tests/test_widgets.py"):
            existing = conn.execute(
                "SELECT id FROM ci_files WHERE path = ?", (path,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
                    "VALUES (?, 'python', ?, ?, ?)",
                    (path, b"\x00" * 32, now_ms, now_ms),
                )
            test_id = conn.execute(
                "SELECT id FROM ci_files WHERE path = ?", (path,)
            ).fetchone()["id"]
            parser_id = conn.execute(
                "SELECT id FROM ci_files WHERE path = 'src/parser.py'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) "
                "VALUES (?, 'src.parser', ?, 1)",
                (test_id, parser_id),
            )
        out = find_tests(conn, "src/parser.py", project_root=root)

    ranked = [t["path"] for t in out["tests"]]
    assert ranked[0] == "tests/test_parser.py"
    assert set(ranked) >= {"tests/test_helpers.py", "tests/test_widgets.py"}
    # Scores are strictly ordered, and the winner carries both channels.
    assert out["tests"][0]["score"] > out["tests"][1]["score"]


def test_find_tests_matches_name_tokens_not_substrings(tmp_path):
    # "cli" is a substring of "client" — the old substring rule made every
    # test_client.py a candidate test for cli.py.
    root = _project(tmp_path)
    with connect(_paths.db_path(root)) as conn:
        now_ms = int(time.time() * 1000)
        for path in ("src/cli.py", "tests/test_client.py", "tests/test_cli.py"):
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
                "VALUES (?, 'python', ?, ?, ?)",
                (path, b"\x00" * 32, now_ms, now_ms),
            )
        out = find_tests(conn, "src/cli.py", project_root=root)

    assert [t["path"] for t in out["tests"]] == ["tests/test_cli.py"]


def test_find_tests_ignores_structural_stems(tmp_path):
    # Every package has an __init__.py; sharing that name says nothing about
    # sharing a subject.
    root = _project(tmp_path)
    with connect(_paths.db_path(root)) as conn:
        now_ms = int(time.time() * 1000)
        for path in ("src/pkg/__init__.py", "tests/other/__init__.py"):
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
                "VALUES (?, 'python', ?, ?, ?)",
                (path, b"\x00" * 32, now_ms, now_ms),
            )
        out = find_tests(conn, "src/pkg/__init__.py", project_root=root)

    assert out["tests"] == []


def test_module_graph_never_returns_edges_to_files_it_omitted(tmp_path):
    # The node cap stops the frontier mid-expansion; edges discovered past it
    # would otherwise point at files absent from `nodes`.
    root = _project(tmp_path)
    with connect(_paths.db_path(root)) as conn:
        now_ms = int(time.time() * 1000)
        ids = {}
        for i in range(12):
            path = f"src/m{i}.py"
            ids[path] = conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
                "VALUES (?, 'python', ?, ?, ?)",
                (path, b"\x00" * 32, now_ms, now_ms),
            ).lastrowid
        root_id = conn.execute(
            "SELECT id FROM ci_files WHERE path = 'src/parser.py'"
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) "
            "VALUES (?, 'src.m0', ?, 1)",
            (root_id, ids["src/m0.py"]),
        )
        for i in range(11):
            conn.execute(
                "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) "
                f"VALUES (?, 'src.m{i + 1}', ?, 1)",
                (ids[f"src/m{i}.py"], ids[f"src/m{i + 1}.py"]),
            )
        graph = module_graph(conn, "src/parser.py", depth=5, limit=4, project_root=root)

    node_paths = {n["path"] for n in graph["nodes"]}
    assert len(node_paths) <= 4
    for edge in graph["edges"]:
        assert edge["from"] in node_paths, edge
        assert edge["to"] in node_paths, edge
    # And the caller is told the view was cut short rather than guessing.
    assert graph["truncated"]["edges_omitted"] > 0


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
        hits = recall(conn, "codex", limit=3)

    assert out == {"ok": True, "topic": "codex wiring"}
    assert hits[0]["topic"] == "codex wiring"
    assert hits[0]["tags"] == ["codex"]
    assert hits[0]["type"] == "finding"
    assert hits[0]["type_source"] == "default"
    assert hits[0]["score_kind"] == "cosine_similarity"
    assert hits[0]["min_score"] == 0.25
    assert hits[0]["created_at"].endswith("Z")
    assert hits[0]["updated_at"].endswith("Z")


def test_recall_filters_weak_matches_by_default(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        remember(conn, "parser note", "Symbol parser internals.", tags=["parser"])
        filtered = recall(conn, "codex", limit=3)
        raw = recall(conn, "codex", limit=3, min_score=0)

    assert filtered == []
    assert raw[0]["topic"] == "parser note"
    assert raw[0]["score"] == 0.0


def test_recall_does_not_infer_type_from_content_words(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        remember(conn, "fixtures", "Testing strategy uses fixtures.")
        hits = recall(conn, "fixtures", limit=1)

    assert hits[0]["type"] == "finding"
    assert hits[0]["type_source"] == "default"


def test_recall_classifies_rules_and_formats_dates(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        remember(conn, "optimizer gate", "Persistent rule: validate on real data.", tags=["ken-rule"])
        hits = recall(conn, "optimizer", limit=1)

    assert hits[0]["type"] == "persistent_rule"
    assert hits[0]["type_source"] == "legacy_tag"
    rendered = format_recall_hits(hits)
    assert "persistent_rule" in rendered
    assert "updated " in rendered


def test_remember_accepts_explicit_kind(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        out = remember(conn, "optimizer gate", "Validate on real data.", kind="persistent_rule")
        hits = recall(conn, "optimizer", limit=1)

    assert out == {"ok": True, "topic": "optimizer gate"}
    assert hits[0]["tags"] == ["kind:persistent_rule"]
    assert hits[0]["type"] == "persistent_rule"
    assert hits[0]["type_source"] == "explicit"


def test_forget_deletes_finding_by_topic(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])
        resp = forget(conn, "codex wiring")
        missing = forget(conn, "codex wiring")
        hits = recall(conn, "codex symbol", limit=3)

    assert resp == {"ok": True, "topic": "codex wiring", "deleted": 1}
    assert missing == {"ok": False, "topic": "codex wiring", "deleted": 0}
    assert hits == []


def test_list_findings_returns_recent_and_filters_tags(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex.", tags=["codex"])
        remember(conn, "optimizer gate", "Persistent rule.", tags=["ken-rule"])
        hits = list_findings(conn, limit=10, tag="codex")

    assert [hit["topic"] for hit in hits] == ["codex wiring"]
    assert hits[0]["type"] == "finding"


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


def test_remember_cli_accepts_kind(monkeypatch, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())

    rc = main(
        [
            "remember",
            "--path",
            str(root),
            "--kind",
            "hypothesis",
            "optimizer idea",
            "Try validating on real data.",
        ]
    )

    assert rc == 0
    with connect(_paths.db_path(root)) as conn:
        hits = recall(conn, "optimizer", limit=1)
    assert hits[0]["type"] == "hypothesis"


def test_forget_cli_deletes_finding(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())
    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])

    rc = main(["forget", "--path", str(root), "codex wiring"])

    assert rc == 0
    assert "forgot: codex wiring" in capsys.readouterr().out
    with connect(_paths.db_path(root)) as conn:
        assert list_findings(conn) == []


def test_findings_cli_lists_saved_findings(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())
    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])

    rc = main(["findings", "--path", str(root), "--tag", "codex"])

    assert rc == 0
    assert "codex wiring" in capsys.readouterr().out


def test_recall_cli_prints_json(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())
    with connect(_paths.db_path(root)) as conn:
        remember(conn, "codex wiring", "Use --codex to repair hooks.", tags=["codex"])

    rc = main(["recall", "--path", str(root), "--json", "codex"])

    assert rc == 0
    assert '"topic": "codex wiring"' in capsys.readouterr().out


def test_recall_cli_reports_no_relevant_findings(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    monkeypatch.setattr("ken.memory.get_embedder", lambda: FakeEmbedder())
    with connect(_paths.db_path(root)) as conn:
        remember(conn, "parser note", "Symbol parser internals.", tags=["parser"])

    rc = main(["recall", "--path", str(root), "codex"])

    assert rc == 0
    assert "no relevant findings (min_score=0.250)" in capsys.readouterr().out


def test_looks_like_test_requires_a_camelcase_boundary():
    # `endswith("test.java")` on a lowercased name also swallows Latest.java,
    # Contest.cs, protest.cs and Greatest.kt — none of which are tests.
    from ken.search import _looks_like_test

    for path in ("src/Latest.java", "src/Contest.cs", "src/protest.cs",
                 "src/latest.kt", "src/Greatest.kt", "src/manifest.java"):
        assert _looks_like_test(path) is False, path
    for path in ("src/UserServiceTest.java", "src/FooTests.cs", "src/BarSpec.kt",
                 "pkg/thing_test.go", "lib/a_spec.rb", "ui/x.test.ts",
                 "tests/t.py", "__tests__/a.js", "spec/b.rb"):
        assert _looks_like_test(path) is True, path


def test_test_basename_preserves_case_for_camelcase_tokens():
    # Lowercasing here would collapse the name into one token and silently
    # disable token matching for every Java/C#/Kotlin test.
    from ken.search import _name_tokens, _test_basename

    base = _test_basename("src/UserServiceIntegrationTest.java")
    assert _name_tokens(base) == {"user", "service", "integration", "test"}


def test_sql_prefilter_is_a_superset_of_looks_like_test():
    # _find_tests_for_row narrows in SQL before calling _looks_like_test; if a
    # real test file fails the LIKE it is invisible no matter what.
    from ken.search import _looks_like_test

    paths = [
        "src/UserServiceTest.java", "src/FooTests.cs", "src/BarSpec.kt",
        "pkg/thing_test.go", "lib/a_spec.rb", "ui/x.test.ts", "ui/y.spec.tsx",
        "tests/t.py", "__tests__/a.js", "spec/b.rb", "a/test_c.py",
        "m/n_test.rs", "d/e_test.dart", "f/g.test.mjs",
    ]
    for path in paths:
        assert _looks_like_test(path), path
        lowered = path.lower()
        assert "test" in lowered or "spec" in lowered, path


def test_find_tests_finds_camelcase_java_tests(tmp_path):
    root = _project(tmp_path)
    with connect(_paths.db_path(root)) as conn:
        now_ms = int(time.time() * 1000)
        for path in ("src/UserService.java", "src/UserServiceTest.java",
                     "src/Latest.java"):
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
                "VALUES (?, 'java', ?, ?, ?)",
                (path, b"\x00" * 32, now_ms, now_ms),
            )
        out = find_tests(conn, "src/UserService.java", project_root=root)

    assert [t["path"] for t in out["tests"]] == ["src/UserServiceTest.java"]
    assert out["tests"][0]["reason"] == "named for target"
