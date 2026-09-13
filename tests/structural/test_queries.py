from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.model import FactIndex, IR
from ken.structural.query import QueryBudget, evaluate_pattern, parse_pattern
from ken.structural.semantic import link_project
from ken.structural.selectors import parse_query


@pytest.fixture
def graph():
    return link_project([lower_source('''
user_name: str = "Ada"
class Service:
    def search(self, position: int, filter_name: str, *args, **kwargs) -> str:
        return user_name
    def other(self, x): return x
''', "python", "sample.py")])


def test_user_selector_example_with_regex_union_and_bound_roles(graph):
    query = '''
var_declaration(name: /^user.*/i, type: [str, unknown]) as $user;
method(name: /^search$/, return_type: [str, unknown]) as $method {
    has_parameter(pos: 0, type: int) as $position;
    has_parameter(pos: *, type: str, name: /^FILTER.*$/i) as $filter;
}
require $method READS $user;
'''
    result = evaluate_pattern(graph, query)
    assert result.complete
    assert len(result.matches) == 1
    assert set(result.matches[0]["bindings"]) == {"$user", "$method", "$position", "$filter"}


@pytest.mark.parametrize("query,expected", [
    ('method(name: other, return_type: unknown) as $m;', 1),
    ('method(name: search, return_type: unknown) as $m;', 0),
    ('method(name: *, return_type: *) as $m;', 2),
    ('method(name: /^SEARCH$/i) as $m;', 1),
    ('method(name: /^SEARCH$/) as $m;', 0),
    ('method(name: /search/) as $m { has_parameter(parameter_kind: variadic_keyword) as $p; }', 1),
    ('method(name: search) as $same; method(name: other) as $same;', 0),
])
def test_selector_predicates(graph, query, expected):
    assert len(evaluate_pattern(graph, query).matches) == expected


@pytest.mark.parametrize("bad", [
    'method(name: /[/) as $m;', 'method(name: /x/z) as $m;',
    'method(name: []) as $m;', 'method(name: x', 'strange(name: x) as $m;',
    'has_parameter(pos: 0) as $p;', 'method(name: search) as $m { parameter(type: int) as $p; }',
    'require $a FLOW{0,999} $b', 'count >=2 $x IS CLASS', 'require $x IS',
    'require $x IS CLASS\ndifferent $x $unbound',
])
def test_invalid_queries_rejected(bad):
    with pytest.raises(ValueError):
        parse_query(bad)


def test_relation_joins_preserve_identity_and_different():
    ir = IR("p", "mixed")
    ir.add("a", "LINK", "b")
    ir.add("b", "LINK", "c")
    ir.add("c", "LINK", "c")
    result = evaluate_pattern(ir, 'require $x LINK $y\nrequire $y LINK $z\ndifferent $x $z')
    assert {tuple(m["bindings"][v] for v in ("$x", "$y", "$z")) for m in result.matches} == {("a", "b", "c"), ("b", "c", "c")}


@pytest.mark.parametrize("relation,expected", [("LINK{2,3}", {"c", "d"}), ("LINK+", {"b", "c", "d"}), ("LINK{3,3}", {"d"})])
def test_bounded_paths(relation, expected):
    ir = IR("p", "mixed")
    for a, z in zip("abc", "bcd"):
        ir.add(a, "LINK", z)
    result = evaluate_pattern(ir, f'require a {relation} $target')
    assert {m["bindings"]["$target"] for m in result.matches} == expected


def test_count_distinct_with_joined_predicates():
    ir = IR("p", "mixed")
    ir.add("C", "IS", "CLASS")
    for i in range(3):
        ir.add("C", "HAS_METHOD", str(i))
        ir.add(str(i), "WRITES", "f")
        if i < 2:
            ir.add(str(i), "RETURNS", "C")
    query = 'require $c IS CLASS\ncount >=2 $c HAS_METHOD $m distinct=$m where $m WRITES _ and $m RETURNS $c'
    assert len(evaluate_pattern(ir, query).matches) == 1
    assert not evaluate_pattern(ir, query.replace(">=2", ">=3")).matches


def test_optional_evidence_ranks_without_relaxing_required():
    ir = IR("p", "mixed", capabilities={"syntax"})
    ir.add("a", "IS", "CLASS")
    ir.add("b", "IS", "CLASS")
    ir.add("b", "EXTRA", "yes")
    result = evaluate_pattern(ir, 'require $c IS CLASS\noptional $c EXTRA yes')
    assert result.matches[0]["bindings"]["$c"] == "b"
    assert result.matches[0]["evidence_score"] == 1
    assert result.matches[1]["evidence_score"] == .5


def test_semantic_absence_is_unknown_without_complete_resolution():
    ir = IR("p", "mixed", capabilities={"syntax"})
    ir.add("a", "IS", "CALL")
    result = evaluate_pattern(ir, 'require $c IS CALL\nforbid $c TARGET _')
    assert result.matches[0]["status"] == "unknown"
    assert "complete_type_resolution" in result.matches[0]["unknown"]


@pytest.mark.parametrize("field", ["max_rows", "max_states", "max_matches"])
def test_budget_never_returns_proven_empty(field):
    ir = IR("p", "mixed")
    for i in range(20): ir.add(str(i), "IS", "CLASS")
    result = evaluate_pattern(ir, 'require $c IS CLASS', QueryBudget(**{field: 1}))
    assert not result.complete
    assert any(u.startswith("budget:") for u in result.unknown)


def test_regex_execution_is_bounded():
    ir = IR("p", "mixed")
    ir.add("a", "ENTITY", "CALLABLE", name="a" * 100_000 + "!")
    result = evaluate_pattern(ir, 'method(name: /^(a+)+$/) as $m;', QueryBudget(timeout_ms=1000))
    assert not result.complete
    assert result.unknown == ["budget:regex_timeout"]


def test_endpoint_index_avoids_full_relation_scan():
    ir = IR("p", "mixed")
    for i in range(10_000): ir.add(str(i), "LINK", str(i+1))
    index = FactIndex(ir)
    result = evaluate_pattern(index, 'require 4321 LINK $x')
    assert len(result.matches) == 1
    assert result.stats["rows_examined"] == 1


def test_variant_reports_which_idiom_matched():
    ir = IR("p", "mixed")
    ir.add("a", "IS", "CLASS")
    ir.add("a", "EXTRA", "yes")
    result = evaluate_pattern(ir, 'require $c IS CLASS\nvariant one\nrequire $c EXTRA no\nend\nvariant two\nrequire $c EXTRA yes\nend')
    assert [m["variant"] for m in result.matches] == ["two"]


def test_selector_different_rejects_unbound_roles():
    with pytest.raises(ValueError, match="bound"):
        parse_query('method(name: *) as $a;\ndifferent $a $missing')


def test_variant_optional_score_is_normalized():
    graph = IR("p", "mixed")
    graph.add("a", "IS", "CLASS")
    graph.add("a", "EXTRA", "yes")
    result = evaluate_pattern(graph, 'require $a IS CLASS\nvariant shape\noptional $a EXTRA yes\nend')
    assert result.matches[0]["evidence_score"] == 1
