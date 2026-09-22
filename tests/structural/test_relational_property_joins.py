"""Property postings reduce joins without changing proofs or unknown rows."""

import json

import pytest

from ken.structural.model import Entity, FactIndex, IR
from ken.structural.query import Clause, QueryBudget
from ken.structural.relational import Executor, Node, Query
from ken.structural.relational_predicates import fact_constraints
from ken.structural.relational_resources import ExecutionResources


def fact(subject, relation, object_):
    return Node("fact", Clause("require", subject, relation, object_))


def comparable(result):
    def normalize(value):
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, list):
            return sorted((normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
        return value
    return normalize({k: result[k] for k in ("matches", "unknown", "complete")})


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("operation", ["literal", "=="])
@pytest.mark.parametrize("mode", ["possible", "strict"])
def test_correlated_property_join_preserves_missing_modality_and_evidence(reverse, operation, mode):
    ir = IR("sample", "python")
    ir.entities["seed"] = Entity("seed", "CALLABLE", "chosen", "sample", 1, 1)
    ir.add("root", "DECLARES", "seed", evidence="seed-proof")
    for i in range(200):
        identifier = f"method{i}"
        ir.entities[identifier] = Entity(identifier, "CALLABLE", f"noise{i}", "sample", i, i)
        ir.add(f"owner{i}", "HAS_METHOD", identifier, evidence=f"proof{i}",
               **({"modality": "may"} if i == 0 else {}))
    ir.entities["method0"].name = "chosen"
    # Missing entity: the ENTITY fact fallback has a missing name, not a denial.
    del ir.entities["method1"]
    ir.add("method1", "ENTITY", "CALLABLE")
    first, second = "$seed.name", "$method.name"
    if reverse:
        first, second = second, first
    query = Query("q", [fact("root", "DECLARES", "$seed"),
                        fact("$owner", "HAS_METHOD", "$method"),
                        Node("where", (first, operation, second))],
                  {"method": "$method"})
    index = FactIndex(ir)
    reference = Executor(index, {}, evidence_mode=mode)
    reference.reference = True
    expected = reference.execute(query)
    actual = Executor(index, {}, evidence_mode=mode).execute(query)
    assert comparable(actual) == comparable(expected)
    assert actual["stats"]["rows_examined"] < 10


@pytest.mark.parametrize("values", [("a|b", "a"), ("a", "a|b"),
                                    (True, "true"), ("true", True), (None, "x")])
@pytest.mark.parametrize("operation", ["literal", "=="])
@pytest.mark.parametrize("reverse", [False, True])
def test_property_join_keeps_literal_alternatives_and_boolean_direction(values, operation, reverse):
    ir = IR("sample", "python")
    for identifier, value in zip(("seed", "candidate"), values):
        ir.entities[identifier] = Entity(identifier, "CALLABLE", identifier, "sample", 1, 1,
                                         {"flag": value})
    ir.add("root", "DECLARES", "seed")
    ir.add("root", "HAS_METHOD", "candidate")
    terms = ("$candidate.flag", "$seed.flag") if reverse else ("$seed.flag", "$candidate.flag")
    query = Query("q", [fact("root", "DECLARES", "$seed"),
                        fact("root", "HAS_METHOD", "$candidate"),
                        Node("where", (terms[0], operation, terms[1]))],
                  {"candidate": "$candidate"})
    index = FactIndex(ir)
    expected = Executor(index, {}, evidence_mode="possible")
    expected.reference = True
    assert comparable(Executor(index, {}, evidence_mode="possible").execute(query)) == comparable(expected.execute(query))


@pytest.mark.parametrize("barrier", ["any", "match", "count", "optional", "not", "source_body", "source_usages"])
def test_property_prefilter_never_reads_past_a_barrier(barrier):
    engine = Executor(FactIndex(IR("", "")), {})
    node = fact("$owner", "HAS_METHOD", "$method")
    where = Node("where", ("$method.name", "literal", "$seed.name"))
    assert fact_constraints(engine, node, [Node(barrier), where], {"$seed": "seed"}, None) is None


def test_posting_build_cancellation_does_not_poison_shared_snapshot():
    ir = IR("sample", "python")
    for i in range(100):
        ir.add("owner", "HAS_METHOD", str(i))
        ir.add(str(i), "ENTITY", "CALLABLE", name="match" if i == 0 else "noise")
    index = FactIndex(ir)
    resources = ExecutionResources(index)
    query = Query("q", [fact("$owner", "HAS_METHOD", "$method"),
                        Node("where", ("$method.name", "literal", '"match"'))],
                  {"method": "$method"})
    first = Executor(index, {}, QueryBudget(max_states=5), resources=resources)
    assert not first.execute(query)["complete"]
    first.close()
    second = Executor(index, {}, resources=resources)
    result = second.execute(query)
    assert result["complete"] and len(result["matches"]) == 1
    assert resources.property_postings.stats()["retained_bytes"] <= 4_000_000
