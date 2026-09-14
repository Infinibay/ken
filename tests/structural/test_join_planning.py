"""Join planning must change cost, never answers.

The engine chooses the order in which it evaluates the clauses of a conjunction.
Three properties are load-bearing and easy to break:

* the same conjunction written in a different order returns the same rows;
* a clause filtered by an attribute is planned before a generator that would
  multiply rows the filter is about to remove;
* ``different`` is applied as soon as both roles exist, instead of after the
  join it would have pruned.

Each test asserts the rows first and the cost second, so a future planner change
that buys speed by dropping matches fails here.
"""
from __future__ import annotations

from ken.structural.kenql import Engine, query_graph
from ken.structural.model import IR
from ken.structural.rules import _parsed_query

UNITS = 200
METHODS = 30
CALLS = 400


def graph(units: int = UNITS, methods: int = METHODS, calls: int = CALLS,
          calls_per_method: int = 1) -> IR:
    ir = IR("p", "python", capabilities={"syntax"})
    for i in range(units):
        ir.add(f"K{i}", "ENTITY", "CLASS", name=f"K{i}")
        ir.add(f"K{i}", "IS", "CLASS")
        for j in range(methods):
            method = f"K{i}m{j}"
            ir.add(f"K{i}", "HAS_METHOD", method)
            ir.add(method, "ENTITY", "CALLABLE", name=f"m{j}")
            for k in range(calls_per_method):
                ir.add(method, "HAS_CALL", f"c{(i + j + k) % calls}")
    for i in range(calls):
        ir.add(f"c{i}", "ENTITY", "CALL", name=f"call{i}")
        ir.add(f"c{i}", "IS", "CALL")
    ir.add("K0m0", "HAS_CALL", "enc0")
    ir.add("enc0", "ENTITY", "CALL", name="encode_now")
    ir.add("enc0", "IS", "CALL")
    return ir


def run(source: str, **shape):
    return Engine(query_graph(graph(**shape)), {}, None).execute(_parsed_query(source, {}))


def rows(result) -> list[tuple]:
    return sorted(tuple(sorted(match["bindings"].items())) for match in result["matches"])


def test_a_conjunction_returns_the_same_rows_in_any_order():
    forward = run('query qa { require $a IS CLASS; require $a HAS_METHOD $m; emit $a, $m; }')
    backward = run('query qb { require $a HAS_METHOD $m; require $a IS CLASS; emit $a, $m; }')
    assert len(rows(forward)) == UNITS * METHODS
    assert rows(forward) == rows(backward)


def test_an_attribute_filter_is_planned_before_the_generator_it_filters():
    """``call(name: /^encode/)`` matches one entity out of CALLS.

    Rating that clause by ``len(rows('ENTITY'))`` makes the planner enumerate
    every call in the graph for every candidate method, which is how a rare
    combination used to turn into millions of intermediate rows.
    """
    result = run('query qc { require $u HAS_METHOD $m; call(name: /^encode/) as $c;'
                 ' require $m HAS_CALL $c; emit $u, $m, $c; }')
    assert len(rows(result)) == 1
    assert result["stats"]["rows_examined"] < 2 * CALLS


def test_the_planner_ignores_where_different_is_written():
    """``different`` is a filter: the engine applies it as soon as both roles exist.

    Written last, the naive plan builds the ``HAS_CALL`` product and then removes
    every row whose roles are equal; the engine must reach the same rows and the
    same number of visited states from either spelling.
    """
    shape = {"units": 20, "methods": 8, "calls": 50, "calls_per_method": 5}
    early = run('query qe { require $u IS CLASS; require $u HAS_METHOD $a;'
                ' require $u HAS_METHOD $b; different $a $b;'
                ' require $a HAS_CALL $x; require $b HAS_CALL $y; emit $u, $a, $b, $x, $y; }', **shape)
    late = run('query ql { require $u IS CLASS; require $u HAS_METHOD $a;'
               ' require $u HAS_METHOD $b; require $a HAS_CALL $x; require $b HAS_CALL $y;'
               ' different $a $b; emit $u, $a, $b, $x, $y; }', **shape)
    assert rows(early) and rows(early) == rows(late)
    assert early["stats"]["states"] == late["stats"]["states"]
