"""Necessary source evidence prunes joins without suppressing unknown matches."""

import json
from types import MappingProxyType, SimpleNamespace

import pytest

from ken.kql2 import source_candidates
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.query import Clause
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor, Node
from ken.structural.semantic import link_project

QUERY = """language "kql/2"; module candidates;
pattern detect(out Callable $method, out Field $table, out Parameter $value) {
  type $owner {
    field $table { effective: true; }
    method $method { param $value {} body { insert $value into $table; } }
  }
}
query results { use detect(method: $method, table: $table, value: $value); select $method,$table,$value; }
"""
SOURCE = """class Registry:
 def add(self, value): self.table.append(value)
 def noise(self, value): self.other = value
"""


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        return (
            sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
            if all(isinstance(item, dict) for item in items)
            else items
        )
    return value


@pytest.mark.parametrize(
    "coverage", ["structured", "partial", "missing_status", "missing_entry"]
)
@pytest.mark.parametrize("mode", ["strict", "possible"])
def test_candidates_preserve_complete_results_evidence_and_uncertainty(coverage, mode):
    ir = link_project([lower_source(SOURCE, "python", "sample.py")])
    noise = next(entity.id for entity in ir.entities.values() if entity.name == "noise")
    if coverage == "partial":
        for fact in ir.facts:
            if fact.subject == noise and fact.relation == "CFG_STATUS":
                fact.object = "partial"
    elif coverage != "structured":
        relation = "CFG_STATUS" if coverage == "missing_status" else "CFG_ENTRY"
        ir.facts = [
            fact
            for fact in ir.facts
            if not (fact.subject == noise and fact.relation == relation)
        ]
    index = query_graph(ir)
    query = compile_source(QUERY)
    optimized = Executor(index, {}, evidence_mode=mode)
    reference = Executor(index, {}, evidence_mode=mode)
    reference.reference = True
    actual, expected = optimized.execute(query), reference.execute(query)
    for key in ("matches", "unknown", "complete"):
        assert canonical(actual[key]) == canonical(expected[key])
    assert actual["complete"] and actual["matches"]
    if coverage != "structured" and mode == "possible":
        assert any(match["status"] == "unknown" for match in actual["matches"])


def test_requirement_registration_is_independent_of_catalog_pattern_names(monkeypatch):
    def extension(owner, clause):
        return source_candidates.OwnerRequirement(owner, ("CUSTOM_RELATION",))

    monkeypatch.setattr(
        source_candidates,
        "OWNER_REQUIREMENTS",
        MappingProxyType({"extension": extension}),
    )
    body = SimpleNamespace(
        owner="method", clauses=[SimpleNamespace(kind="extension", role="place")]
    )
    declaration = Node("fact", Clause("require", "$method", "ENTITY", '"CALLABLE"'))
    nodes = [declaration, Node("source_body", body)]
    requirement = source_candidates.SourceCandidatePlanner.owner_requirement(nodes)
    assert requirement == source_candidates.OwnerRequirement(
        "$method", ("CUSTOM_RELATION",)
    )
    assert (
        source_candidates.SourceCandidatePlanner.owner_requirement(
            [Node("any"), *nodes]
        )
        is None
    )


def test_prerequisites_do_not_escape_body_alternatives():
    declaration = Node("fact", Clause("require", "$method", "ENTITY", '"CALLABLE"'))
    body = SimpleNamespace(
        owner="method", clauses=[SimpleNamespace(kind="either", role="")]
    )
    assert (
        source_candidates.SourceCandidatePlanner.owner_requirement(
            [declaration, Node("source_body", body)]
        )
        is None
    )


@pytest.mark.parametrize(
    "coverage", ["structured", "partial", "missing_call", "missing_status"]
)
@pytest.mark.parametrize("mode", ["strict", "possible"])
@pytest.mark.parametrize("after_body", [False, True])
@pytest.mark.parametrize("capture", [False, True])
def test_named_call_prefilter_preserves_unknowns_and_replans_after_body(
    coverage, mode, after_body, capture
):
    prefix = "callable $factory { body { return 1; } }" if after_body else ""
    call = 'call $occurrence { name: ["wanted", "alternative"]; resolution: any; };'
    body = "let $result = " + call + " return $result;" if capture else call
    query = compile_source(
        """language "kql/2"; module named_calls;
    pattern detect(out Callable $method) {
    """
        + prefix
        + """
      callable $method { body { """
        + body
        + """ } }
    }
    query results { use detect(method: $method); select $method; }
    """
    )
    ir = link_project(
        [
            lower_source(
                """def factory(): return 1

def selected(): return wanted()
def noise(): other()
""",
                "python",
                "sample.py",
            )
        ]
    )
    noise = next(entity.id for entity in ir.entities.values() if entity.name == "noise")
    if coverage == "partial":
        for fact in ir.facts:
            if fact.subject == noise and fact.relation == "CFG_STATUS":
                fact.object = "partial"
    elif coverage == "missing_status":
        ir.facts = [
            fact
            for fact in ir.facts
            if not (fact.subject == noise and fact.relation == "CFG_STATUS")
        ]
    elif coverage == "missing_call":
        ir.entities = {
            key: entity
            for key, entity in ir.entities.items()
            if not (entity.kind == "CALL" and entity.attrs.get("owner") == noise)
        }
    index = query_graph(ir)
    optimized = Executor(index, {}, evidence_mode=mode, profile=True)
    reference = Executor(index, {}, evidence_mode=mode)
    reference.reference = True
    actual, expected = optimized.execute(query), reference.execute(query)
    for key in ("matches", "unknown", "complete"):
        assert canonical(actual[key]) == canonical(expected[key])
    assert actual["complete"] and actual["matches"]
    assert any(
        metric.get("source_prefilter", {}).get("call_names")
        == ("wanted", "alternative")
        for metric in optimized.profile
    )
