"""The ``at least N distinct $role { ... }`` cardinality clause.

KQL 2 states an existential cardinality requirement over the solutions of a nested
block -- "this pattern holds for at least two different values of the role" -- which
no body pattern can express. The clause is the readable spelling of the counting
node; the legacy ``tally distinct`` spelling keeps parsing and lowers to the same
node, so both are checked here side by side.
"""
import re

import pytest

from ken.kql2.compiler import compile, CompileError
from ken.kql2.syntax import parse, ParseError
from ken.kql2.graph import relational_plan
from ken.kql2.execution import execute
from ken.structural.relational import Executor
from ken.structural.model import IR, Fact, FactIndex

HEADER = 'language "kql/2"; module example; '

TWO_METHODS = [Fact('p', 'ENTITY', 'CLASS', {'name': 'Work'}),
               Fact('p', 'HAS_METHOD', 'm1', {}),
               Fact('p', 'HAS_METHOD', 'm2', {})]
ONE_METHOD = [Fact('p', 'ENTITY', 'CLASS', {'name': 'Work'}),
              Fact('p', 'HAS_METHOD', 'm1', {})]


def run(source, facts):
    program = compile(parse(HEADER + source))
    graph = IR('example.py', 'python', facts=facts, capabilities=set())
    return Executor(FactIndex(graph), {}, evidence_mode='strict').execute(relational_plan(program))


def test_two_distinct_values_satisfy_the_requirement():
    result = run('query q { edge ENTITY($p, "CLASS"); '
                 'at least 2 distinct $m { edge HAS_METHOD($p, $m); }; select $p; }', TWO_METHODS)
    assert result['complete']
    assert [m['bindings'] for m in result['matches']] == [{'$p': 'p'}]


def test_one_value_does_not_satisfy_the_requirement():
    result = run('query q { edge ENTITY($p, "CLASS"); '
                 'at least 2 distinct $m { edge HAS_METHOD($p, $m); }; select $p; }', ONE_METHOD)
    assert result['complete'] and result['matches'] == []


def test_the_bound_is_the_written_count():
    result = run('query q { edge ENTITY($p, "CLASS"); '
                 'at least 3 distinct $m { edge HAS_METHOD($p, $m); }; select $p; }', TWO_METHODS)
    assert result['complete'] and result['matches'] == []


def test_the_legacy_counting_spelling_still_lowers_to_the_same_node():
    new = run('query q { edge ENTITY($p, "CLASS"); '
              'at least 2 distinct $m { edge HAS_METHOD($p, $m); }; select $p; }', TWO_METHODS)
    old = run('query q { edge ENTITY($p, "CLASS"); '
              'tally distinct $m >= 2 { edge HAS_METHOD($p, $m); }; select $p; }', TWO_METHODS)
    assert [m['bindings'] for m in new['matches']] == [m['bindings'] for m in old['matches']] != []


@pytest.mark.parametrize('clause', ['at least distinct $m { edge HAS_METHOD($p, $m); };',
                                    'at least 2 $m { edge HAS_METHOD($p, $m); };',
                                    'at least 2 distinct $m;'])
def test_the_clause_requires_a_count_a_distinct_a_role_and_a_block(clause):
    with pytest.raises(ParseError):
        parse(HEADER + 'query q { edge ENTITY($p, "CLASS"); ' + clause + ' select $p; }')
