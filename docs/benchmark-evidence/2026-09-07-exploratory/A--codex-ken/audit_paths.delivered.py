"""Reproduce path containment checks using only this checkout and stdlib.

Loads actual function ASTs without importing optional product dependencies.
MCP registration/transport is excluded; SQLite uses a minimal in-memory table.
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent


def load_functions(relative, names, namespace):
    path = REPO / relative
    tree = ast.parse(path.read_text(), filename=str(path))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[
        ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)


ns = {"Path": Path}
load_functions("src/ken/_paths.py", ["resolve_project_path"], ns)
ns["_paths"] = SimpleNamespace(resolve_project_path=ns["resolve_project_path"])
load_functions("src/ken/search.py", ["file_snippets", "_normalize_index_path",
               "_file_row", "_read_line_range"], ns)
load_functions("src/ken/mcp/server.py", ["ken_read", "_project_relative_path",
               "_impl_ken_file_snippets"], ns)

with TemporaryDirectory(prefix=".audit-paths-", dir=REPO) as temporary:
    base = Path(temporary)
    root = base / "project"
    (root / "src").mkdir(parents=True)
    outside = base / "project-sibling"
    outside.mkdir()
    (root / "src/ok.py").write_text("inside\n")
    (outside / "secret.py").write_text("outside\n")
    (root / "internal").symlink_to(root / "src", target_is_directory=True)
    (root / "external").symlink_to(outside, target_is_directory=True)
    (root / "broken-in").symlink_to(root / "missing.py")
    (root / "broken-out").symlink_to(outside / "missing.py")
    ns["_PROJECT_ROOT"] = root
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE ci_files (id INTEGER, path TEXT, language TEXT, "
                 "symbol_count INTEGER, indexed_at TEXT)")
    conn.executemany("INSERT INTO ci_files VALUES (?, ?, 'python', 0, '')",
                     [(1, "src/ok.py"), (2, "deleted.py")])
    ns["_conn"] = lambda: conn
    cases = [
        ("relative", "src/ok.py", "read"),
        ("absolute internal", root / "src/ok.py", "read"),
        ("internal ..", "src/../src/ok.py", "read"),
        ("parent escape", "../project-sibling/secret.py", "reject"),
        ("absolute sibling prefix", outside / "secret.py", "reject"),
        ("internal symlink", "internal/ok.py", "read"),
        ("external symlink", "external/secret.py", "reject"),
        ("external symlink missing leaf", "external/missing.py", "reject"),
        ("missing internal", "missing.py", "unindexed"),
        ("missing absolute internal", root / "missing.py", "unindexed"),
        ("missing external", outside / "missing.py", "reject"),
        ("broken internal symlink", "broken-in", "unindexed"),
        ("broken external symlink", "broken-out", "reject"),
        ("deleted indexed file", "deleted.py", "empty"),
    ]
    for label, supplied, expected in cases:
        try:
            result = ns["ken_read"](str(supplied), include=["source"],
                                    start_line=1, end_line=1, max_chars=100)
        except ValueError as error:
            assert str(error).startswith("path escapes project root:")
            actual = "reject"
        else:
            assert result["ok"] is True
            source = result["source"]
            if source["ok"] is False:
                assert source["error"] == "file not indexed"
                actual = "unindexed"
            else:
                code = source["snippets"][0]["code"]
                assert code in ("", "1: inside")
                actual = "empty" if code == "" else "read"
        assert actual == expected, (label, actual, expected)
        print(f"PASS {label}: {actual}")
    conn.close()
print(f"{len(cases)} cases passed; temporary fixtures removed.")
