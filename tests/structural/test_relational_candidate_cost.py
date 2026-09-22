"""Index selection must not scan a posting list it will discard."""

import pytest

from ken.structural.model import IR, FactIndex
from ken.structural.query import Clause
from ken.structural.relational import Executor, Row


class UnscannableList(list):
    def __iter__(self):
        raise AssertionError("a larger candidate bucket must only be counted")


@pytest.mark.parametrize("endpoint", ["METHOD", "METHOD|FUNCTION"])
def test_bound_entity_does_not_copy_larger_attribute_bucket(endpoint):
    ir = IR("example", "python")
    ir.add("chosen", "ENTITY", "METHOD", static=False)
    for i in range(1000):
        ir.add(f"noise{i}", "ENTITY", "METHOD", static=False)
    index = FactIndex(ir)
    bucket = index.attr_rows("ENTITY", "static", "false")
    index._by_attr[("ENTITY", "static")]["false"] = UnscannableList(bucket)
    engine = Executor(index, {})
    clause = Clause(
        "require", "$method", "ENTITY", endpoint, [("static", "=", "false")]
    )
    hits = engine.facts(clause, Row({"$method": "chosen"}))
    assert len(hits) == 1
    assert hits[0].bindings == {"$method": "chosen"}
    assert engine.rows == 1


def test_finite_kind_union_does_not_copy_larger_posting_lists():
    ir = IR("example", "python")
    ir.add("chosen", "ENTITY", "METHOD")
    for i in range(1000):
        ir.add(f"noise{i}", "ENTITY", "CLASS")
    index = FactIndex(ir)
    bucket = index.rows("ENTITY", object="CLASS")
    index._by_object[("ENTITY", "CLASS")] = UnscannableList(bucket)
    engine = Executor(index, {})
    clause = Clause("require", "$method", "ENTITY", "CLASS|METHOD")
    hits = engine.facts(clause, Row({"$method": "chosen"}))
    assert len(hits) == 1
    assert engine.rows == 1


def test_smaller_alternative_union_still_filters_and_preserves_order():
    ir = IR("example", "python")
    for name, kind in [
        ("a", "CLASS"),
        ("b", "METHOD"),
        ("c", "FUNCTION"),
        ("d", "VALUE"),
    ]:
        ir.add(name, "ENTITY", kind, name=name)
    engine = Executor(FactIndex(ir), {})
    clause = Clause("require", "$entity", "ENTITY", "METHOD|FUNCTION|METHOD")
    assert [hit.bindings["$entity"] for hit in engine.facts(clause, Row())] == [
        "b",
        "c",
    ]
    clause = Clause("require", "$entity", "ENTITY", "_", [("name", "=", "c|a")])
    assert [hit.bindings["$entity"] for hit in engine.facts(clause, Row())] == [
        "c",
        "a",
    ]
