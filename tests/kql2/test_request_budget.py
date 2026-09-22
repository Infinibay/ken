"""The public timeout bounds acquisition too, even a non-cooperative lock."""

import time

import pytest

from ken.checks.report import query_view
from ken.kql2.compiler import CompileError
from ken.kql2.service import search
from ken.kql2.syntax import ParseError
from ken.structural_store.acquisition import AcquisitionLock

QUERY = 'language "kql/2"; module t; query q {class $c {} select $c.name;}'


@pytest.mark.parametrize(
    "backend,database",
    [
        ("indexed", "store.sqlite"),
        ("exploration", "syntax.sqlite"),
    ],
)
def test_deadline_includes_blocking_acquisition_and_releases_worker(
    tmp_path, backend, database
):
    (tmp_path / "a.py").write_text("class A: pass\n")
    query = (
        QUERY
        if backend == "indexed"
        else 'language "kql/2"; module t; query q {node $n {native_kind:"class_definition";} select $n.line;}'
    )
    with_lock = AcquisitionLock(
        tmp_path / ".ken/structural/v2" / database, enabled=True
    )
    try:
        start = time.monotonic()
        result = search(tmp_path, query, backend=backend, timeout_ms=600)
        elapsed = time.monotonic() - start
    finally:
        with_lock.close()
    assert 0.5 <= elapsed < 1.5
    assert not result["complete"] and not result["coverage_complete"]
    compact = query_view(result)
    assert compact["reason"] == ("timeout_ms" if backend == "indexed" else "timeout")
    assert compact["stopped_phase"] == "acquisition"
    assert compact["timing"]["total_ms"] >= 500
    # The interrupted process cannot retain the lock or corrupt the next search.
    recovered = search(tmp_path, query, backend=backend, timeout_ms=3000)
    assert recovered["complete"] and recovered["rows"] == (
        [["A"]] if backend == "indexed" else [[1]]
    )


@pytest.mark.parametrize(
    "query,error",
    [
        ('language "kql/2"; broken', ParseError),
        (
            'language "kql/2"; module t; query q { class $c { unknown:true; } select $c; }',
            CompileError,
        ),
    ],
)
def test_worker_preserves_compiler_diagnostics(tmp_path, query, error):
    with pytest.raises(error) as failure:
        search(tmp_path, query, timeout_ms=3000)
    assert failure.value.span.source == "<query>"
    assert failure.value.code
    assert not (tmp_path / ".ken/structural/v2/store.sqlite").exists()


def test_partial_rows_and_real_timings_survive_supervision(tmp_path):
    (tmp_path / "a.py").write_text("class A: pass\nclass B: pass\n")
    result = search(tmp_path, QUERY, timeout_ms=3000, max_rows=1)
    assert not result["complete"] and len(result["rows"]) == 1
    compact = query_view(result)
    assert compact["timing"]["total_ms"] >= compact["timing"]["build_ms"]
    assert compact["timing"]["timeout_ms"] == 3000


def test_scope_does_not_walk_sibling_trees(tmp_path, monkeypatch):
    from pathlib import Path

    (tmp_path / "selected").mkdir()
    (tmp_path / "selected/a.py").write_text("class A: pass\n")
    (tmp_path / "unrelated").mkdir()
    original = Path.iterdir

    def guarded(self):
        assert self != tmp_path / "unrelated", (
            "scoped search traversed an unrelated tree"
        )
        return original(self)

    monkeypatch.setattr(Path, "iterdir", guarded)
    result = search(tmp_path, QUERY, path="selected")
    assert result["rows"] == [["A"]]


def test_killed_parser_releases_its_lease(tmp_path):
    import sqlite3

    (tmp_path / "big.py").write_text(
        "".join(f"def f{i}():\n return {i}\n" for i in range(10000))
    )
    result = search(tmp_path, QUERY, timeout_ms=700)
    assert not result["complete"]
    assert result["analysis"]["stopped_phase"] in {"parse", "persist"}
    database = tmp_path / ".ken/structural/v2/store.sqlite"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM k2_leases").fetchone()[0] == 0
    (tmp_path / "small.py").write_text("class B: pass\n")
    recovered = search(tmp_path, QUERY, path="small.py", timeout_ms=3000)
    assert recovered["rows"] == [["B"]] and not recovered["analysis"]["ephemeral"]
