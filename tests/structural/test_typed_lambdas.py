"""Java/C# lambdas are separate callable scopes, including void targets."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def graph(language, expression):
    source = f'class A {{ object Wrap(Handler next) {{ return {expression}; }} }}'
    if language == 'java': source = source.replace('object', 'Object')
    result = link_project([lower_source(source, language, 'sample')])
    assert not result.diagnostics
    return result


@pytest.mark.parametrize('language,arrow', [('java', '->'), ('csharp', '=>')])
@pytest.mark.parametrize('parameters', ['x', '(x)', '(Request x)'])
def test_lambda_parameter_and_outer_receiver(language, arrow, parameters):
    g = graph(language, f'{parameters} {arrow} next.handle(x)')
    closure = next(e.id for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression')
    params = [f.object for f in g.facts if f.subject == closure and f.relation == 'HAS_PARAMETER']
    assert [g.entities[p].name for p in params] == ['x']
    outer = next(e.id for e in g.entities.values() if e.name == 'Wrap')
    assert any(f.subject == closure and f.relation == 'OWNED_BY' and f.object == outer for f in g.facts)
    assert any(f.subject == outer and f.relation == 'RETURNS' and f.object == closure for f in g.facts)
    call = next(f.object for f in g.facts if f.subject == closure and f.relation == 'HAS_CALL')
    assert not any(f.subject == outer and f.relation == 'HAS_CALL' and f.object == call for f in g.facts)
    assert any(f.subject == call and f.relation == 'ARGUMENT' and f.object == params[0] for f in g.facts)
    assert any(f.subject == closure and f.relation == 'BODY_VALUE' and f.object == call for f in g.facts)
    assert not any(f.subject == closure and f.relation == 'RETURNS' for f in g.facts)


@pytest.mark.parametrize('language,arrow', [('java', '->'), ('csharp', '=>')])
def test_explicit_lambda_return_belongs_to_lambda(language, arrow):
    g = graph(language, f'() {arrow} {{ return next.handle(); }}')
    closure = next(e.id for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression')
    returned = [f.object for f in g.facts if f.subject == closure and f.relation == 'RETURNS']
    assert len(returned) == 1 and g.entities[returned[0]].kind == 'CALL'


@pytest.mark.parametrize('language,arrow', [('java', '->'), ('csharp', '=>')])
def test_parameter_shadowing_does_not_capture_outer(language, arrow):
    # C# rejects this redeclaration at compile time; the lexical IR must still
    # preserve the source scopes rather than attributing calls to another role.
    g = graph(language, f'next {arrow} next.handle()')
    closure = next(e.id for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression')
    parameter = next(f.object for f in g.facts if f.subject == closure and f.relation == 'HAS_PARAMETER')
    call = next(f.object for f in g.facts if f.subject == closure and f.relation == 'HAS_CALL')
    assert any(f.subject == call and f.relation == 'RECEIVER' and f.object == parameter for f in g.facts)


@pytest.mark.parametrize('language,source', [
    ('java', 'class A { Runnable action = () -> work(); }'),
    ('csharp', 'class A { Action action = () => Work(); }'),
])
def test_field_lambda_is_not_class_method(language, source):
    g = link_project([lower_source(source, language, 'sample')])
    closure = next(e.id for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression')
    assert not any(f.relation == 'HAS_METHOD' and f.object == closure for f in g.facts)
    assert not any(f.subject == closure and f.relation == 'RETURNS' for f in g.facts)


def test_csharp_nested_async_does_not_leak_to_outer_lambda():
    g = graph('csharp', 'x => async y => await Work(x, y)')
    closures = sorted((e for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression'), key=lambda e: e.attrs['start_byte'])
    assert [e.attrs['async_'] for e in closures] == [False, True]


def test_cpp_lambda_body_has_separate_owner():
    g = link_project([lower_source('auto f() { return [](int x) { return work(x); }; }', 'cpp', 'sample')])
    assert not g.diagnostics
    closure = next(e.id for e in g.entities.values() if e.attrs.get('native_kind') == 'lambda_expression')
    assert any(f.subject == closure and f.relation == 'RETURNS' for f in g.facts)
