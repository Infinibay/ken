"""Middleware-shaped adapters require correlated returned closure evidence."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCES = {
    'go': '''package p
import "net/http"
func wrap(next http.Handler) http.Handler {
 return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { next.ServeHTTP(w,r) })
}''',
    'python': '''def wrap(next):
 def handler(request):
  return next.handle(request)
 return adapt(handler)
''',
    'javascript': 'function wrap(next) { return adapt(function(request) { return next.handle(request); }); }',
    'typescript': 'function wrap(next: Handler) { return adapt((request: Request) => next.handle(request)); }',
}


def matches(source, language):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.adapted-continuation-wrapper', registry)], registry=registry)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_adapted_object_continuation(language):
    assert len(matches(SOURCES[language], language)) == 1


@pytest.mark.parametrize('language', SOURCES)
def test_renaming_preserves_structure(language):
    source = SOURCES[language].replace('wrap', 'decorate').replace('next', 'proceed')
    assert len(matches(source, language)) == 1


@pytest.mark.parametrize('language', SOURCES)
def test_other_receiver_is_not_continuation(language):
    assert not matches(SOURCES[language].replace('next.', 'other.'), language)


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
def test_function_continuation(language):
    assert matches(SOURCES[language].replace('next.handle(', 'next('), language)


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_nonreturned_adapter_does_not_match(language):
    assert not matches(SOURCES[language].replace('return adapt', 'adapt'), language)


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_shadowed_parameter_is_not_outer_continuation(language):
    source = SOURCES[language].replace('next.handle(request)', 'request.handle(request)')
    assert not matches(source, language)


def test_go_function_continuation_adapter():
    source = '''package p
type Handler func(int) int
func wrap(next func(int) int) Handler { return Handler(func(x int) int { return next(x) }) }'''
    assert matches(source, 'go')


def test_unrelated_returned_adapter_does_not_capture_local_handler():
    source = '''def wrap(next):
 def handler(request):
  return next.handle(request)
 adapt(handler)
 return adapt(other)
'''
    assert not matches(source, 'python')


def test_sibling_handler_is_not_owned_by_factory():
    source = '''def handler(request):
 return next.handle(request)
def wrap(next):
 return adapt(handler)
'''
    assert not matches(source, 'python')


@pytest.mark.parametrize('language,source', [
    ('go', 'package p; type H func(int) int; func wrap(next func(int) int) H { fn := func(x int) int { return next(x) }; return H(fn) }'),
    ('python', 'def wrap(next):\n fn = lambda x: next(x)\n return adapt(fn)\n'),
    ('javascript', 'function wrap(next) { const fn = x => next(x); return adapt(fn); }'),
    ('typescript', 'function wrap(next: Handler) { const fn = (x: Request) => next.handle(x); return adapt(fn); }'),
])
def test_local_handler_binding(language, source):
    assert matches(source, language)
    assert not matches(source.replace('adapt(fn)', 'adapt(other)').replace('H(fn)', 'H(other)'), language)

@pytest.mark.parametrize('language',['python','javascript','typescript','go'])
@pytest.mark.parametrize('mode',['alias','overwritten','overwritten_after_return','conditional_binding','earlier_replaced'])
def test_adapted_handler_uses_the_current_local_callable(language,mode):
    if language=='python':
        declaration=' fn = lambda x: next(x)\n'
        middle={'alias':' chosen = fn\n','overwritten':' fn = other\n',
                'overwritten_after_return':'','conditional_binding':'', 'earlier_replaced':''}[mode]
        if mode=='conditional_binding': declaration=' if flag:\n '+declaration
        if mode=='earlier_replaced': declaration=' fn = other\n'+declaration
        returned='chosen' if mode=='alias' else 'fn'
        source='def wrap(next, flag, other):\n'+declaration+middle+' return adapt('+returned+')\n'
        if mode=='overwritten_after_return': source+=' fn = other\n'
    else:
        declaration='let fn = x => next(x);'
        if language=='go': declaration='fn := func(x int) int {return next(x)};'
        middle={'alias':'let chosen=fn;','overwritten':'fn=other;',
                'overwritten_after_return':'','conditional_binding':'','earlier_replaced':''}[mode]
        if language=='go': middle=middle.replace('let chosen=','chosen:=')
        if mode=='conditional_binding': declaration='if (flag) {'+declaration+'};'
        if mode=='earlier_replaced': declaration=('fn := other; fn = func(x int) int {return next(x)};' if language=='go' else 'let fn=other; fn=x => next(x);')
        returned='chosen' if mode=='alias' else 'fn'
        body=declaration+middle+'return adapt('+returned+');'
        if mode=='overwritten_after_return': body+='fn=other;'
        source=('package p; type Handler func(int) int; func adapt(fn Handler) Handler {return fn}; func wrap(next Handler, flag bool, other Handler) Handler {'+body+'}' if language=='go'
                else 'function wrap(next, flag, other){'+body+'}')
    assert bool(matches(source,language)) is (mode in ('alias','overwritten_after_return','earlier_replaced'))
