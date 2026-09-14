"""Adapter ``functional-adapter``: a callable adapting the input contract.

The variant is a published rule, so the test goes through the registry name
``adapter#functional-adapter``.

What separates this from ``decorator#callable-wrapper`` is the adaptation: the
wrapper invokes the captured callable with **two distinct arguments**, each
obtained by indexing its single input parameter. A pass-through wrapper with one
argument is the Decorator variant, not this one.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'adapter#functional-adapter'

SOURCES = {
    'python': ('''def adapt(inner):
    def wrapped(pair):
        return inner(pair[0], pair[1])
    return wrapped
''', 'a.py'),
    'javascript': ('''function adapt(inner) {
  return function wrapped(pair) {
    return inner(pair[0], pair[1]);
  };
}
''', 'a.js'),
    'typescript': ('''function adapt(inner: (a: number, b: number) => number): (pair: number[]) => number {
  return function wrapped(pair: number[]): number {
    return inner(pair[0], pair[1]);
  };
}
''', 'a.ts'),
    'java': ('''import java.util.function.IntBinaryOperator;
import java.util.function.IntUnaryOperator;
class Adapters {
  static IntUnaryOperator adapt(IntBinaryOperator inner) {
    return pair -> inner.applyAsInt(pair[0], pair[1]);
  }
}
''', 'A.java'),
    'csharp': ('''using System;
class Adapters {
  static Func<int[],int> Adapt(Func<int,int,int> inner) {
    return pair => inner(pair[0], pair[1]);
  }
}
''', 'A.cs'),
    'cpp': ('''#include <functional>
#include <vector>
std::function<int(std::vector<int>)> adapt(std::function<int(int,int)> inner) {
  return [inner](std::vector<int> pair) { return inner(pair[0], pair[1]); };
}
''', 'a.cpp'),
    'go': ('''package adapter

func Adapt(inner func(int, int) int) func([]int) int {
	return func(pair []int) int {
		return inner(pair[0], pair[1])
	}
}
''', 'a.go'),
    'rust': ('''pub fn adapt<F: Fn(i32, i32) -> i32>(inner: F) -> impl Fn(&[i32]) -> i32 {
    move |pair: &[i32]| inner(pair[0], pair[1])
}
''', 'a.rs'),
}

PASSTHROUGH = '''def adapt(inner):
    def wrapped(value):
        return inner(value)
    return wrapped
'''

CONSTANT_ARGUMENTS = '''def adapt(inner):
    def wrapped(pair):
        return inner(1, 2)
    return wrapped
'''

NOT_CAPTURED = '''def other(a, b):
    return a + b

def adapt(inner):
    def wrapped(pair):
        return other(pair[0], pair[1])
    return wrapped
'''

IMMEDIATE = '''def adapt(inner):
    return inner(1, 2)
'''

NOT_RETURNED = '''def adapt(inner):
    def wrapped(pair):
        return inner(pair[0], pair[1])
    return 0
'''


def detect(language, source, path):
    graph = link_project([lower_source(source, language, path)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
def test_adapter_splitting_one_input_into_two_arguments_is_detected(language):
    source, path = SOURCES[language]
    matches = detect(language, source, path)
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    assert bindings['$factory'] != bindings['$wrapped']
    assert '/CALLABLE:' in bindings['$wrapped']


def test_passthrough_wrapper_is_rejected():
    """One argument passed through is Decorator, not this variant."""
    assert not detect('python', PASSTHROUGH, 'a.py')


def test_constant_arguments_are_rejected():
    """The two arguments must come from the input parameter, not constants."""
    assert not detect('python', CONSTANT_ARGUMENTS, 'a.py')


def test_adapting_an_uncaptured_callable_is_rejected():
    assert not detect('python', NOT_CAPTURED, 'a.py')


def test_immediate_call_without_a_wrapper_is_rejected():
    assert not detect('python', IMMEDIATE, 'a.py')


def test_wrapper_not_returned_by_the_factory_is_rejected():
    assert not detect('python', NOT_RETURNED, 'a.py')


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'adapter')
    row = next(v for v in rule.variants if v['id'] == 'functional-adapter')
    assert sorted(row['languages']) == sorted(SOURCES)
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'INDEX' in row['query'] and 'CAPTURES' in row['query']
