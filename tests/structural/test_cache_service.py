from __future__ import annotations

import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from ken.structural.cache import DEFAULT_CACHE_MB, IRCache
from ken.structural.service import build_project, patterns, search
from .gof_sources import PYTHON


def test_default_cache_budget_is_500_decimal_mb(tmp_path):
    cache = IRCache(tmp_path / "cache.sqlite")
    assert DEFAULT_CACHE_MB == 500
    assert cache.limit == 500_000_000
    cache.close()


def test_disabled_cache_does_not_write(tmp_path):
    path = tmp_path / "missing" / "cache.sqlite"
    cache = IRCache(path, 0)
    cache.put("x", {"a": 1})
    assert cache.get("x") is None
    assert not path.parent.exists()


def test_cache_roundtrip_and_content_addressing(tmp_path):
    cache = IRCache(tmp_path / "cache.sqlite", 1)
    cache.put("one", {"unicode": "árbol", "data": [1, 2]})
    assert cache.get("one") == {"unicode": "árbol", "data": [1, 2]}
    assert cache.get("missing") is None
    assert cache.stats()["hits"] == 1
    assert IRCache.key("ab", "c") != IRCache.key("a", "bc")
    assert IRCache.key("v1", "code") != IRCache.key("v2", "code")
    cache.close()


def test_cache_eviction_honors_physical_budget(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = IRCache(path, .15)
    for i in range(30):
        cache.put(str(i), {"data": os.urandom(10_000).hex()})
        assert path.stat().st_size <= 150_000
    assert cache.evictions > 0
    assert cache.get("29") is not None
    assert cache.get("0") is None
    cache.close()


def test_oversized_entry_bypasses_cache(tmp_path):
    cache = IRCache(tmp_path / "cache.sqlite", .05)
    cache.put("huge", {"data": os.urandom(100_000).hex()})
    assert cache.get("huge") is None
    cache.close()


def test_eviction_reuses_freed_pages_without_flushing_the_entire_cache(tmp_path):
    import random

    path = tmp_path / "cache.sqlite"
    cache = IRCache(path, .15)
    random_bytes = random.Random(42)
    for i in range(20):
        before = cache.evictions
        cache.put(str(i), {"data": random_bytes.randbytes(10_000).hex()})
        assert path.stat().st_size <= cache.limit
        if cache.evictions > before:
            assert cache.evictions - before <= 2
            assert cache.get(str(i - 1)) is not None
    assert cache.evictions > 0
    cache.close()


def test_one_graph_can_use_more_than_half_the_cache_budget(tmp_path):
    import random

    path = tmp_path / "cache.sqlite"
    cache = IRCache(path, 1)
    value = {"data": random.Random(42).randbytes(600_000).hex()}
    cache.put("graph", value)
    assert cache.get("graph") == value
    assert path.stat().st_size <= cache.limit
    assert cache.error == ""
    cache.close()


def test_corrupt_cache_is_disposable(tmp_path):
    path = tmp_path / "cache.sqlite"
    path.write_bytes(b"not a database")
    cache = IRCache(path, 1)
    assert cache.get("x") is None
    assert cache.error


def test_concurrent_cache_writers_do_not_corrupt_database(tmp_path):
    path = tmp_path / "cache.sqlite"
    # Initialize once, then independent connections mirror separate Ken processes.
    IRCache(path, 1).close()
    def write(i):
        cache = IRCache(path, 1)
        cache.put(str(i), {"n": i})
        cache.close()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(20)))
    cache = IRCache(path, 1)
    assert all(cache.get(str(i)) == {"n": i} for i in range(20))
    cache.close()


def test_cache_can_be_downsized(tmp_path):
    path = tmp_path / "cache.sqlite"
    cache = IRCache(path, 1)
    for i in range(20): cache.put(str(i), {"data": os.urandom(5000).hex()})
    cache.close()
    smaller = IRCache(path, .05)
    assert path.stat().st_size <= 50_000
    smaller.close()


def test_warm_project_cache_reuses_linked_graph(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text(PYTHON["builder"])
    first, cold = build_project(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("unchanged content should not be parsed or linked again")
    monkeypatch.setattr("ken.structural.service.lower_source", forbidden)
    monkeypatch.setattr("ken.structural.service.link_project", forbidden)
    second, warm = build_project(tmp_path)
    assert second.to_dict() == first.to_dict()
    assert warm["cache"]["hits"] == 1


def test_changes_invalidate_cache_even_with_preserved_mtime(tmp_path):
    file = tmp_path / "a.py"
    file.write_text("class One: pass")
    old = file.stat()
    first, _ = build_project(tmp_path)
    file.write_text("class Two: pass")
    os.utime(file, ns=(old.st_atime_ns, old.st_mtime_ns))
    second, _ = build_project(tmp_path)
    assert first.to_dict() != second.to_dict()
    assert any(e.name == "Two" for e in second.entities.values())


def test_deleted_files_leave_no_stale_graph_nodes(tmp_path):
    (tmp_path / "a.py").write_text("class One: pass")
    (tmp_path / "b.py").write_text("class Two: pass")
    build_project(tmp_path)
    (tmp_path / "b.py").unlink()
    graph, analysis = build_project(tmp_path)
    assert analysis["files"] == ["a.py"]
    assert not any(e.path == "b.py" for e in graph.entities.values())


def test_project_config_environment_and_cli_precedence(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("pass")
    (tmp_path / ".ken").mkdir()
    config = tmp_path / ".ken/structural.json"
    config.write_text(json.dumps({"cache": {"max_mb": 3}}))
    assert build_project(tmp_path)[1]["cache"]["max_bytes"] == 3_000_000
    monkeypatch.setenv("KEN_STRUCTURAL_CACHE_MB", "2")
    assert build_project(tmp_path)[1]["cache"]["max_bytes"] == 2_000_000
    assert build_project(tmp_path, cache_mb=0)[1]["cache"]["max_bytes"] == 0


def test_directory_summary_counts_distinct_matching_files(tmp_path):
    directory = tmp_path / "builders"
    directory.mkdir()
    for name in ["one.py", "two.py"]:
        (directory / name).write_text(PYTHON["builder"])
    result = patterns(tmp_path, ["builder"], cache_mb=0)
    group = result["directories"][0]
    assert group["analyzed_files"] == 2
    assert group["patterns"][0]["matching_files"] == 2
    assert group["patterns"][0]["share"] == 1


def test_gitignored_and_unsupported_files_report_coverage(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "a.py").write_text("pass")
    (tmp_path / "ignored.py").write_text("raise RuntimeError()")
    # Ruby used to be the example of an unsupported file; it has a frontend now,
    # so this pins the *reporting* contract with a language that has none.
    (tmp_path / "a.swift").write_text("print(1)")
    _, analysis = build_project(tmp_path, cache_mb=0)
    assert analysis["files"] == ["a.py"]
    assert not analysis["coverage_complete"]
    assert analysis["skipped"] == [{"path": "a.swift", "reason": "no structural frontend"}]


@pytest.mark.parametrize("option", [{"max_files": 1}, {"max_file_bytes": 3}])
def test_scan_budgets_report_skipped_files(tmp_path, option):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("class A: pass")
    _, analysis = build_project(tmp_path, cache_mb=0, **option)
    assert analysis["skipped"] and not analysis["coverage_complete"]


def test_scope_cannot_escape_project(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        build_project(tmp_path, path="../elsewhere", cache_mb=0)


def test_bad_query_fails_before_creating_cache(tmp_path):
    with pytest.raises(ValueError):
        search(tmp_path, 'method(name: /[/) as $m')
    assert not (tmp_path / ".ken").exists()


def test_corrupt_serialized_ir_is_rebuilt(tmp_path):
    import sqlite3
    import zlib
    (tmp_path / "a.py").write_text("class A: pass")
    build_project(tmp_path)
    with sqlite3.connect(tmp_path / ".ken/structural-cache.sqlite") as conn:
        conn.execute("UPDATE entries SET value=?", (zlib.compress(b'{}'),))
    graph, analysis = build_project(tmp_path)
    assert any(e.name == "A" for e in graph.entities.values())
    assert analysis["cache"]["misses"] >= 1


def test_the_scan_has_no_file_ceiling_unless_one_is_asked_for(tmp_path):
    """A default ceiling silently reported a partial answer as a whole one.

    The old default was 2000 files: iluwatar (213 directories) reported 2000
    analysed files and 42 skipped ones nobody asked to skip. The ceiling is now
    opt-in and always visible in ``analysis.skipped``.
    """
    from ken.structural import service

    for index in range(5):
        (tmp_path / f"f{index}.py").write_text(f"class C{index}:\n    def m(self): return {index}\n",
                                                encoding="utf-8")
    _, analysis = service.build_project(tmp_path, path=".", cache_mb=0)
    assert len(analysis["files"]) == 5
    assert analysis["skipped"] == []
    assert analysis["coverage_complete"] is True

    _, capped = service.build_project(tmp_path, path=".", cache_mb=0, max_files=2)
    assert len(capped["files"]) == 2
    assert {item["reason"] for item in capped["skipped"]} == {"max_files"}
    assert capped["coverage_complete"] is False
