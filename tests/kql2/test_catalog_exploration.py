"""Catalog port preserves semantic evidence, not only finding counts."""

import pytest

from examples.bench.pattern_search import semantic_result
from ken.kql2.exploration.catalog_index import CatalogIndex
from ken.kql2.exploration.records import Records, encode
from ken.structural.frontend import lower_source
from ken.structural.model import IR, Fact
from ken.structural.query_view import query_graph
from ken.structural.service import patterns
from ken.structural_store import Store
from tests.kql2.test_graph_columns import stored
from tests.structural.gof_sources import JAVA, PYTHON, TYPESCRIPT
from tests.structural.gof_sources_ruby import RUBY


@pytest.mark.parametrize(
    "language,extension,fixtures",
    [
        ("python", ".py", PYTHON),
        ("java", ".java", JAVA),
        ("typescript", ".ts", TYPESCRIPT),
        ("ruby", ".rb", RUBY),
    ],
)
@pytest.mark.parametrize("name", sorted(JAVA))
def test_catalog_evidence_matches_indexed_backend(
    tmp_path, language, extension, fixtures, name
):
    (tmp_path / ("source" + extension)).write_text(fixtures[name])
    expected = patterns(tmp_path, [name], backend="indexed", profile=True)
    actual = patterns(tmp_path, [name], backend="exploration", profile=True)
    assert semantic_result(actual["findings"]) == semantic_result(expected["findings"])
    assert actual["complete"] == expected["complete"]
    assert actual["incomplete"] == expected["incomplete"]
    assert actual["analysis"]["pattern_engine"]["backend"] == "exploration"


def test_numeric_indexes_preserve_duplicates_order_and_nulls():
    rows = [("b", None, -1), ("a", "", 2), ("b", "", -3), ("b", "", -3)]
    blob = encode(rows, 3, {0, 1}, lambda: None)
    records = Records(blob, 3, {0, 1})
    assert [records.row(i) for i in records.select({0: "b", 1: ""})] == rows[2:]
    assert not records.cells.flags.writeable


def test_attribute_buckets_ignore_role_names_but_preserve_bound_endpoints():
    from ken.structural.query import Clause

    ir = IR("a", "python", view="query", facts=[
        Fact("a", "ENTITY", "CALLABLE", {"constructor": True}),
        Fact("b", "ENTITY", "CALLABLE", {"constructor": True}),
        Fact("c", "ENTITY", "CALLABLE", {"constructor": False}),
    ])
    with Store() as store:
        base = stored(store, ir)
        index = CatalogIndex(base)
        def scan(subject):
            return Clause("require", subject, "ENTITY", "CALLABLE",
                          [("constructor", "literal", "true")])
        assert [f.subject for f in index.candidates(scan("$init"))] == ["a", "b"]
        builds = index.cache.metrics["builds"]
        assert [f.subject for f in index.candidates(scan("$configure"))] == ["a", "b"]
        assert index.cache.metrics["builds"] == builds
        assert [f.subject for f in index.candidates(scan("a"), subject="a")] == ["a"]
        assert [f.subject for f in index.candidates(scan("$init"), subject="b")] == ["b"]
        index.close()
        base.close()


def test_repeated_endpoint_walk_uses_vectors_without_sql(tmp_path):
    with Store() as store:
        base = stored(
            store,
            IR(
                "a",
                "python",
                view="query",
                facts=[Fact(str(i), "R", str(i % 3)) for i in range(100)],
            ),
        )
        index = CatalogIndex(base, revision="fixture")
        assert len(index.rows("R", object="1")) == 33
        statements = []
        store.db.set_trace_callback(statements.append)
        assert [(f.subject, f.object) for f in index.rows("R", subject="4")] == [
            ("4", "1")
        ]
        assert not statements
        index.close()
        base.close()


def test_owner_operations_survive_persistent_bucket_reuse(tmp_path, monkeypatch):
    ir = query_graph(lower_source("def f():\n return g()\n", "python", "a.py")).ir
    with Store() as store:
        base = stored(store, ir)
        owner = next(e.id for e in ir.entities.values() if e.name == "f")
        index = CatalogIndex(
            base, cache_path=tmp_path / "buckets.sqlite", revision="fixture"
        )
        expected = list(index.operations(owner=owner))
        assert expected
        index.close()
        index = CatalogIndex(
            base, cache_path=tmp_path / "buckets.sqlite", revision="fixture"
        )
        monkeypatch.setattr(
            base,
            "operations",
            lambda **kwargs: pytest.fail("warm bucket read SQL operations"),
        )
        assert list(index.operations(owner=owner)) == expected
        assert index.cache.metrics["disk_hits"] == 1
        index.close()
        base.close()


def test_alternatives_prune_before_execution_and_keep_literal_pipes():
    from ken.structural.query import Clause, QuotedTerm

    facts = [Fact(str(i), "ENTITY", "OTHER") for i in range(1000)]
    facts += [Fact("a", "ENTITY", "CLASS"), Fact("b", "ENTITY", "TRAIT")]
    facts += [Fact("c", "ENTITY", "CLASS|TRAIT")]
    with Store() as store:
        base = stored(store, IR("a", "python", view="query", facts=facts))
        index = CatalogIndex(base)
        clause = Clause("require", "$type", "ENTITY", "CLASS|TRAIT|CLASS")
        assert [f.subject for f in index.candidates(clause)] == ["a", "b"]
        literal = Clause("require", "$type", "ENTITY", QuotedTerm('"CLASS|TRAIT"'))
        assert [f.subject for f in index.candidates(literal)] == ["c"]
        assert index.rows("ENTITY", "a") is index.rows("ENTITY", "a")
        index.close()
        base.close()


def test_bucket_revision_and_checksum_rebuild(tmp_path):
    from ken.kql2.exploration.catalog_index import BucketCache

    path = tmp_path / "buckets.sqlite"
    for revision, value in [("first", "old"), ("second", "new")]:
        cache = BucketCache(path, revision)
        records = cache.get(
            ("key",), 1, {0}, lambda value=value: [(value,)], lambda: None
        )
        assert records.row(0) == (value,)
        assert cache.metrics["builds"] == 1
        cache.close()
    cache = BucketCache(path, "second")
    with cache.db:
        cache.db.execute("UPDATE buckets SET digest='damaged'")
    records = cache.get(("key",), 1, {0}, lambda: [("rebuilt",)], lambda: None)
    assert records.row(0) == ("rebuilt",)
    assert cache.metrics["builds"] == 1
    cache.close()


def test_interrupted_encoding_does_not_publish_partial_bucket(tmp_path):
    from ken.kql2.exploration.catalog_index import BucketCache

    cache = BucketCache(tmp_path / "buckets.sqlite", "revision")

    def interrupted():
        yield ("first",)
        raise TimeoutError("query budget")

    with pytest.raises(TimeoutError):
        cache.get(("key",), 1, {0}, interrupted, lambda: None)
    assert cache.db.execute("SELECT count(*) FROM buckets").fetchone()[0] == 0
    assert not cache.memory
    cache.close()


def test_disk_budget_keeps_newest_fitting_buckets(tmp_path):
    from ken.kql2.exploration.catalog_index import BucketCache

    path = tmp_path / "buckets.sqlite"
    size = len(encode([("a",)], 1, {0}, lambda: None))
    cache = BucketCache(path, "revision", disk_bytes=size)
    for value in ("a", "b"):
        cache.get((value,), 1, {0}, lambda value=value: [(value,)], lambda: None)
    cache.close()
    cache = BucketCache(path, "revision", disk_bytes=size)
    assert cache.db.execute("SELECT count(*) FROM buckets").fetchone()[0] == 1
    records = cache.get(
        ("b",), 1, {0}, lambda: pytest.fail("lost newest bucket"), lambda: None
    )
    assert records.row(0) == ("b",)
    cache.close()


def test_modified_source_invalidates_catalog_results_and_buckets(tmp_path):
    path = tmp_path / "source.py"
    path.write_text(PYTHON["singleton"])
    first = patterns(tmp_path, ["singleton"], profile=True)
    path.write_text("def empty():\n    pass\n")
    actual = patterns(tmp_path, ["singleton"], profile=True)
    expected = patterns(tmp_path, ["singleton"], backend="indexed", profile=True)
    assert first["analysis"]["graph_key"] != actual["analysis"]["graph_key"]
    assert actual["analysis"]["pattern_engine"]["buckets"]["disk_hits"] == 0
    assert semantic_result(actual["findings"]) == semantic_result(expected["findings"])
    assert actual["complete"] == expected["complete"]


def test_external_cache_directory_and_disabled_persistence(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "source.py").write_text("def f():\n    return 1\n")
    cache = tmp_path / "cache"
    result = patterns(root, ["singleton"], cache_directory=cache, profile=True)
    assert result["analysis"]["query_index"]["persistent"]
    assert (cache / "pattern-buckets.sqlite").exists()
    assert not (root / ".ken").exists()
    ephemeral = tmp_path / "ephemeral"
    result = patterns(
        root, ["singleton"], cache_directory=ephemeral, cache_mb=0, profile=True
    )
    assert not result["analysis"]["query_index"]["persistent"]
    assert not list(ephemeral.glob("*.sqlite"))


def test_large_relation_fallback_and_attribute_access(monkeypatch):
    from ken.kql2.exploration import catalog_index
    from ken.structural.query import Clause

    monkeypatch.setattr(catalog_index, "MAX_BUCKET_ROWS", 1)
    ir = IR(
        "a",
        "python",
        view="query",
        facts=[
            Fact("a", "R", "A", attrs={"name": "needle"}),
            Fact("b", "R", "B"),
        ],
    )
    with Store() as store:
        base = stored(store, ir)
        index = CatalogIndex(base)
        clause = Clause("require", "$subject", "R", "A|B")
        assert list(index.candidates(clause)) == list(base.candidates(clause))
        assert list(index.attr_rows("R", "name", "needle")) == list(
            base.attr_rows("R", "name", "needle")
        )
        assert index.cache.metrics["fallback"] == 1
        index.close()
        base.close()


def test_cli_profile_exposes_backend_and_operator_costs(tmp_path, capsys):
    import argparse
    import json

    from ken.structural.cli import add_parser, dispatch

    (tmp_path / "source.py").write_text(PYTHON["singleton"])
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers())
    args = parser.parse_args(
        [
            "structural",
            "patterns",
            "--path",
            str(tmp_path),
            "--pattern",
            "singleton",
            "--profile",
        ]
    )
    dispatch(args)
    result = json.loads(capsys.readouterr().out)
    assert result["analysis"]["pattern_engine"]["backend"] == "exploration"
    assert not result["analysis"]["query_cache"]["enabled"]
    assert result["outcomes"]["singleton"]["stats"]["operator_profile"]


def test_selective_union_of_large_relation_is_shared_across_query_roles(monkeypatch):
    from ken.kql2.exploration import catalog_index
    from ken.structural.query import Clause

    monkeypatch.setattr(catalog_index, "MAX_BUCKET_ROWS", 2)
    ir = IR(
        "a",
        "python",
        view="query",
        facts=[
            Fact("a", "ENTITY", "CLASS"),
            Fact("b", "ENTITY", "TRAIT"),
            Fact("c", "ENTITY", "OTHER"),
            Fact("d", "ENTITY", "OTHER"),
        ],
    )
    with Store() as store:
        base = stored(store, ir)
        index = CatalogIndex(base)
        first = Clause("require", "$first", "ENTITY", "CLASS|TRAIT")
        second = Clause("require", "$second", "ENTITY", "CLASS|TRAIT")
        assert [f.subject for f in index.candidates(first)] == ["a", "b"]
        assert [f.subject for f in index.candidates(second)] == ["a", "b"]
        assert index.cache.metrics["builds"] == 1
        assert index.cache.metrics["hits"] == 1
        index.close()
        base.close()
