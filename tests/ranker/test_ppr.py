"""Optional graph ranking: real counterpart wiring and sparse walk semantics."""

import numpy as np
import pytest

from ken.ranker import RankedItem
from ken.ranker.ppr import _build_adjacency, apply_ppr


def test_sparse_walk_matches_weighted_dense_reference(conn, make_file):
    paths = ["a.py", "b.py", "c.py", "isolated.py"]
    ids = [make_file(path) for path in paths]
    for src, dst in [(0, 1), (0, 1), (1, 2)]:
        conn.execute(
            "INSERT INTO ci_imports(from_file_id,to_module,to_file_id,line) VALUES (?, 'module', ?, 1)",
            (ids[src], ids[dst]),
        )
    graph = _build_adjacency(conn, paths, {p: i for i, p in enumerate(paths)})
    transition = np.array([[0, 2/3, 0, 0], [1, 0, 1, 0], [0, 1/3, 0, 0], [0, 0, 0, 0]])
    seed = np.array([0.7, 0, 0, 0.3])
    sparse = dense = seed.copy()
    for _ in range(3):
        sparse = 0.8 * seed + 0.2 * graph.walk(sparse)
        dense = 0.8 * seed + 0.2 * (transition @ dense)
    assert sparse == pytest.approx(dense)


@pytest.mark.parametrize("anchor,neighbor", [("src/a.py", "tests/test_a.py"), ("tests/test_a.py", "src/a.py")])
def test_ppr_resolves_source_test_counterparts(conn, make_file, anchor, neighbor):
    make_file(anchor)
    make_file(neighbor)
    files = [RankedItem(anchor, "file", 3.0)]
    apply_ppr(conn, files)
    assert [(it.target, it.score) for it in files] == [(anchor, 3.0), (neighbor, 0.6)]


def test_ppr_works_without_optional_commit_tables(conn, make_file):
    conn.execute("DROP TABLE cr_commit_files")
    make_file("src/a.py")
    make_file("tests/test_a.py")
    files = [RankedItem("src/a.py", "file", 3.0)]
    apply_ppr(conn, files)
    assert len(files) == 2


def test_sparse_storage_on_large_disconnected_project(conn):
    # A dense implementation would allocate 20 GB for 50k files.
    paths = [f"src/file_{i}.py" for i in range(50_000)]
    graph = _build_adjacency(conn, paths, {p: i for i, p in enumerate(paths)})
    arrays = [graph.source, graph.target, graph.weight, graph.degree]
    assert all(a.ndim == 1 for a in arrays)
    assert sum(a.nbytes for a in arrays) <= len(paths) * 8
    assert not graph.walk(np.ones(len(paths))).any()
