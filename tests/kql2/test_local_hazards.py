"""Demanded hazard evidence must agree with full semantic preparation."""

import pytest

from ken.kql2.service import search

QUERY = """language "kql/2"; module hazards; query hazards_found {
edge HAS_HAZARD($site, $kind); select $site, $kind;
}"""

SOURCES = {
    "defaults.py": "def bad(items=[]):\n return items\ndef good(items=None):\n return [] if items is None else items\n",
    "flow.py": "def flow():\n try:\n  pass\n except:\n  pass\n finally:\n  return None\n print('dead')\n",
    "values.py": "def values():\n x=x\n assert (1,2)\n return 1\n print('dead')\n",
    "other.js": "function f(x) { if(x === NaN) return true; }\n",
}


def test_hazard_profile_agrees_with_full_frontend_evidence_and_reuses_units(tmp_path):
    for path, content in SOURCES.items():
        (tmp_path / path).write_text(content)
    full = search(tmp_path, QUERY, reference=True, cache_mb=20)
    local = search(tmp_path, QUERY, cache_mb=20)
    assert sorted(full["rows"]) == sorted(local["rows"])
    assert len(local["rows"]) >= 5
    assert (
        local["complete"]
        and local["coverage_complete"]
        and not local["unknown_candidates"]
    )
    assert full["optional_evidence"] == local["optional_evidence"]
    assert local["analysis"]["source_profile"] == "local_hazards"
    again = search(tmp_path, QUERY, cache_mb=20)
    assert again["analysis"]["parsed_units"] == 0
    assert again["analysis"]["result_cache"] == "disk_hit"
    # Partial hazard IR is never accepted for an unrelated source query.
    declarations = search(
        tmp_path,
        'language "kql/2"; module t; query q {callable $f {} select $f.name;}',
        cache_mb=20,
    )
    assert declarations["analysis"]["source_profile"] == "full"
    assert len(declarations["rows"]) == 5


def test_hazards_do_not_link_or_lower_full_python_units(tmp_path, monkeypatch):
    from ken.kql2 import graph_execution, service

    def forbidden(*args, **kwargs):
        raise AssertionError("whole-project work is unnecessary")

    (tmp_path / "a.py").write_text(SOURCES["defaults.py"])
    monkeypatch.setattr(graph_execution, "graph_index", forbidden)
    monkeypatch.setattr(service, "lower_source", forbidden)
    result = search(tmp_path, QUERY, cache_mb=0)
    assert len(result["rows"]) == 1 and result["complete"]


def test_hazard_cache_pressure_falls_back_without_evicting_large_graphs(
    tmp_path, monkeypatch
):
    from ken.kql2 import retention
    from ken.structural_store.store import Store

    original = Store.put_unit

    def full(store, *args, **kwargs):
        if store.path is not None:
            raise MemoryError("full semantic cache")
        return original(store, *args, **kwargs)

    def expensive(*args, **kwargs):
        raise AssertionError("do not reclaim a whole semantic graph for cheap hazards")

    (tmp_path / "a.py").write_text(SOURCES["defaults.py"])
    monkeypatch.setattr(Store, "put_unit", full)
    monkeypatch.setattr(retention, "trim", expensive)
    result = search(tmp_path, QUERY, cache_mb=20)
    assert len(result["rows"]) == 1 and result["complete"]
    assert result["analysis"]["ephemeral"]


def test_hazard_parse_errors_do_not_prove_absence(tmp_path):
    (tmp_path / "a.py").write_text("def broken(\n")
    result = search(tmp_path, QUERY, cache_mb=0)
    assert result["rows"] == [] and not result["coverage_complete"]


def test_mixed_graph_query_keeps_full_acquisition(tmp_path):
    (tmp_path / "a.py").write_text(SOURCES["defaults.py"])
    source = QUERY.replace(
        "select $site, $kind;", "edge OWNED_BY($site,$owner); select $site, $kind;"
    )
    result = search(tmp_path, source, cache_mb=0)
    assert result["analysis"]["source_profile"] == "full"
    assert len(result["rows"]) == 1


@pytest.mark.parametrize("content", ["def good(x=None): pass", "def bad(x=[]): pass"])
def test_source_edits_invalidate_hazard_snapshot(tmp_path, content):
    file = tmp_path / "a.py"
    file.write_text("def before(x={}): pass")
    before = search(tmp_path, QUERY, cache_mb=20)
    file.write_text(content)
    after = search(tmp_path, QUERY, cache_mb=20)
    assert len(before["rows"]) == 1
    assert len(after["rows"]) == int("bad" in content)
    assert before["analysis"]["snapshot"] != after["analysis"]["snapshot"]
