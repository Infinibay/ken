"""Returned handlers must preserve lexical callable identity and ownership."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


WRAPPERS = {
 'python': 'def wrap(next):\n def handler(x):\n  return next(x)\n return handler\n',
 'go': 'package p; func wrap(next func(int) int) func(int) int { return func(x int) int { return next(x) } }',
 'javascript': 'function wrap(next) { return function(x) { return next(x); }; }',
 'typescript': 'function wrap(next: (x: number) => number) { return function(x: number) { return next(x); }; }',
}


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
@pytest.mark.parametrize('source', [
 'const wrap = next => request => next(request);',
 'const wrap = (next) => (request) => next(request);',
 'const wrap = next => (request => next(request));',
 'const wrap = next => async request => await next(request);',
])
def test_expression_arrow_wrappers(language, source):
    assert wrapper_matches(source, language)
    assert not wrapper_matches(source.replace('next(request)', 'other(request)'), language)


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_block_arrow_without_return_does_not_return_nested_handler(language):
    assert not wrapper_matches('const wrap = next => { const handler = request => next(request); };', language)
    assert not wrapper_matches('const wrap = next => next => next(1);', language)


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_inner_async_arrow_does_not_mark_factory_async(language):
    graph = lower_source('const wrap = next => async request => await next(request);', language, 'example')
    functions = sorted((e for e in graph.entities.values() if e.kind == 'CALLABLE'), key=lambda e: e.attrs['start_byte'])
    assert [e.attrs['async_'] for e in functions] == [False, True]


def wrapper_matches(source, language):
    graph = link_project([lower_source(source, language, 'example')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.continuation-wrapper', registry)], registry=registry)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language', WRAPPERS)
def test_continuation_wrapper_and_near_misses(language):
    source = WRAPPERS[language]
    assert wrapper_matches(source, language)
    assert wrapper_matches(source.replace('wrap', 'decorate').replace('next', 'proceed'), language)
    assert not wrapper_matches(source.replace('next(x)', 'other(x)'), language)
    assert not wrapper_matches(source.replace('next(x)', 'x'), language)


@pytest.mark.parametrize('language,source', [
 ('python', 'def wrap(next):\n def handler(next):\n  return next(1)\n return handler\n'),
 ('javascript', 'function wrap(next) { return function(next) { return next(1); }; }'),
 ('typescript', 'function wrap(next: (x: number) => number) { return function(next: (x: number) => number) { return next(1); }; }'),
 ('go', 'package p; func wrap(next func(int) int) func(func(int) int) int { return func(next func(int) int) int { return next(1) } }'),
])
def test_shadowed_continuation_is_not_the_captured_parameter(language, source):
    assert not wrapper_matches(source, language)


@pytest.mark.parametrize('language,source', [
 ('go', 'package p; func wrap(next func(int) int) func(int) int { return func(x int) int { return next(x) } }'),
 ('javascript', 'function wrap(next) { return function(x) { return next(x); }; }'),
 ('typescript', 'function wrap(next: (x: number) => number) { return function(x: number) { return next(x); }; }'),
 ('python', 'def wrap(next):\n def handler(x):\n  return next(x)\n return handler\n'),
 ('javascript', 'function wrap(next) { return (x) => { return next(x); }; }'),
])
def test_returned_handler_is_a_callable_and_owns_its_calls(language, source):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    outer = next(e.id for e in graph.entities.values() if e.kind == 'CALLABLE' and e.name == 'wrap')
    returned = {f.object for f in graph.facts if f.subject == outer and f.relation == 'RETURNS'}
    assert len(returned) == 1
    inner = returned.pop()
    assert graph.entities[inner].kind == 'CALLABLE'
    assert any(f.subject == inner and f.relation == 'OWNED_BY' and f.object == outer for f in graph.facts)
    assert not any(f.subject == outer and f.relation == 'HAS_CALL' for f in graph.facts)
    assert any(f.subject == inner and f.relation == 'HAS_CALL' for f in graph.facts)
