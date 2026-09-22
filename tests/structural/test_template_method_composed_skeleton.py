"""Template Method ``composed-skeleton``: fixed sequence over supplied hooks.

The variant is a published rule, so the test goes through the registry name
``template-method#composed-skeleton``.

This is the composition variant: the skeleton receives its hooks as callables
instead of overriding them, and the contract is the sequence itself -- the result
of one hook reaches the argument of the next.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'template-method#composed-skeleton'

SOURCES = {
    'python': ('''def run(prepare, transform, finish):
    value = prepare()
    result = transform(value)
    return finish(result)
''', 's.py'),
    'javascript': ('''function run(prepare, transform, finish) {
  const value = prepare();
  const result = transform(value);
  return finish(result);
}
''', 's.js'),
    'typescript': ('''function run(prepare: () => number, transform: (v: number) => number,
                finish: (v: number) => number): number {
  const value = prepare();
  const result = transform(value);
  return finish(result);
}
''', 's.ts'),
    'java': ('''import java.util.function.IntSupplier;
import java.util.function.IntUnaryOperator;
class Pipeline {
  static int run(IntSupplier prepare, IntUnaryOperator transform, IntUnaryOperator finish) {
    int value = prepare.getAsInt();
    int result = transform.applyAsInt(value);
    return finish.applyAsInt(result);
  }
}
''', 'P.java'),
    'csharp': ('''using System;
class Pipeline {
  static int Run(Func<int> prepare, Func<int,int> transform, Func<int,int> finish) {
    int value = prepare();
    int result = transform(value);
    return finish(result);
  }
}
''', 'P.cs'),
    'cpp': ('''#include <functional>
int run(std::function<int()> prepare, std::function<int(int)> transform,
        std::function<int(int)> finish) {
  int value = prepare();
  int result = transform(value);
  return finish(result);
}
''', 's.cpp'),
    'go': ('''package pipeline

func Run(prepare func() int, transform func(int) int, finish func(int) int) int {
	value := prepare()
	result := transform(value)
	return finish(result)
}
''', 's.go'),
    'rust': ('''pub fn run<P: Fn() -> i32, T: Fn(i32) -> i32, F: Fn(i32) -> i32>(
    prepare: P,
    transform: T,
    finish: F,
) -> i32 {
    let value = prepare();
    let result = transform(value);
    finish(result)
}
''', 's.rs'),
}

RENAMED = '''def pipeline(first, second, third):
    seed = first()
    middle = second(seed)
    return third(middle)
'''

NO_HANDOFF = '''def run(prepare, transform, finish):
    prepare()
    transform(0)
    return finish(0)
'''

ONLY_TWO_HOOKS = '''def run(prepare, transform):
    value = prepare()
    return transform(value)
'''

HOOK_REUSED = '''def run(prepare, transform, finish):
    value = prepare()
    result = transform(value)
    return transform(result)
'''

WRONG_ORDER = '''def run(prepare, transform, finish):
    result = transform(0)
    value = prepare()
    return finish(result)
'''


def detect(language, source, path):
    graph = link_project([lower_source(source, language, path)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
def test_skeleton_composing_three_hooks_is_detected(language):
    source, path = SOURCES[language]
    matches = detect(language, source, path)
    assert len(matches) == 1, language
    hooks = {matches[0]['bindings'][role] for role in ('$prepare', '$transform', '$finish')}
    assert len(hooks) == 3


def test_renamed_hooks_preserve_detection():
    assert len(detect('python', RENAMED, 's.py')) == 1


def test_hooks_without_a_value_handoff_are_rejected():
    assert not detect('python', NO_HANDOFF, 's.py')


def test_skeleton_with_only_two_hooks_is_rejected():
    assert not detect('python', ONLY_TWO_HOOKS, 's.py')


def test_reusing_one_hook_for_two_steps_is_rejected():
    """The sequence must combine three distinct hooks."""
    assert not detect('python', HOOK_REUSED, 's.py')


def test_steps_not_chained_by_value_are_rejected():
    assert not detect('python', WRONG_ORDER, 's.py')


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'template-method')
    row = next(v for v in rule.variants if v['id'] == 'composed-skeleton')
    assert sorted(row['languages']) == sorted(SOURCES)
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'body {' in row['query'] and 'let $prepared = call' in row['query']
    assert 'argument $prepared at 0' in row['query'] and ' != ' in row['query']
    assert 'edge ' not in row['query'] and 'walk ' not in row['query']
