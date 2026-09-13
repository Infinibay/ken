"""Sequential return origins: killed definitions and alias snapshots."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def source(language, statements):
    if language == 'python':
        return 'class Product: pass\ndef build():\n' + ''.join(' '+s+'\n' for s in statements)
    statements = [s.replace('None', 'null').replace('Product()', 'new Product()') for s in statements]
    if language in {'javascript', 'typescript'}:
        body = ';'.join(statements).replace('var ', 'let ')
        return 'class Product {} function build(){'+body+';}'
    body = ';'.join(statements).replace('var ', 'Product ')
    return 'class Product {} class Demo { Product build(){'+body+';} }'


def analyze(language, statements):
    if language == 'python':
        statements = [s.replace('var ', '') for s in statements]
    g = link_project([lower_source(source(language, statements), language, 'sample')])
    assert not g.diagnostics
    created = [g.entities[f.object].name for f in g.facts if f.relation == 'RETURNS_NEW']
    statuses = [(f.object, f.attrs) for f in g.facts if f.relation == 'RETURN_FLOW_STATUS']
    return g, created, statuses


@pytest.mark.parametrize('language', ['python','javascript','typescript','java','csharp'])
@pytest.mark.parametrize('statements,expected', [
    (['var x = Product()', 'return x'], True),
    (['var x = Product()', 'x = None', 'return x'], False),
    (['var x = None', 'x = Product()', 'return x'], True),
    (['var x = Product()', 'var y = x', 'x = None', 'return y'], True),
    (['var x = None', 'var y = x', 'x = Product()', 'return y'], False),
    (['var x = Product()', 'return x', 'x = None'], True),
    (['var x = None', 'return x', 'x = Product()'], False),
    (['var x = None', 'return x', 'return Product()'], False),
])
def test_return_uses_binding_value_at_that_point(language, statements, expected):
    graph, created, statuses = analyze(language, statements)
    assert bool(created) is expected
    assert statuses and all(s == 'supported' for s,_ in statuses)
    origins = [f for f in graph.facts if f.relation == 'RETURN_ORIGIN']
    assert len(origins) == 1
    assert origins[0].attrs['basis'] == 'flow'
    reaches = [f for f in graph.facts if f.relation == 'RETURN_REACHES']
    assert len(reaches) == 1
    targets = {f.subject: f.object for f in graph.facts if f.relation == 'ASSIGNMENT_TARGET'}
    returns = {f.subject: f.object for f in graph.facts if f.relation == 'RETURN_OPERAND'}
    assert targets[reaches[0].object] == returns[reaches[0].subject]


@pytest.mark.parametrize('body', [
    ' x = Product()\n while flag:\n  x = None\n return x\n',
    ' x = Product()\n try:\n  return x\n finally:\n  x = None\n',
    ' x = Product()\n def change():\n  nonlocal x\n  x = None\n change()\n return x\n',
    ' x = Product()\n exec("x = None")\n return x\n',
    ' x = Product()\n yield x\n return x\n',
    ' x = Product()\n x += 1\n return x\n',
    ' x, y = Product(), None\n return x\n',
    ' x = Product()\n (x := None)\n return x\n',
    ' x = Product()\n import math as x\n return x\n',
])
def test_unsupported_flow_does_not_claim_sequential_origins(body):
    graph = link_project([lower_source('class Product: pass\ndef build():\n'+body,'python','sample')])
    assert not graph.diagnostics
    assert not any(f.relation == 'RETURN_ORIGIN' for f in graph.facts)
    assert any(f.relation == 'RETURN_FLOW_STATUS' and f.object == 'unsupported' for f in graph.facts)


def test_compound_assignment_rhs_is_not_the_stored_value():
    graph = link_project([lower_source('function f(){let x=1; x+=2; return x;}','javascript','sample')])
    assert not any(f.relation == 'RETURN_ORIGIN' for f in graph.facts)


def test_shadowed_block_binding_does_not_overwrite_outer_value():
    graph = link_project([lower_source('function f(){let x=1; {let x=2;} return x;}','javascript','sample')])
    assert not any(f.relation == 'RETURN_ORIGIN' for f in graph.facts)


def test_unassigned_alias_is_not_resolved_from_a_future_write():
    graph = link_project([lower_source('function f(){let y=x;let x=1;return y;}','javascript','sample')])
    assert not any(f.relation == 'RETURN_ORIGIN' for f in graph.facts)


def test_bare_return_stops_later_value_returns():
    graph = link_project([lower_source('def f():\n return\n return 1\n','python','sample')])
    assert not any(f.relation == 'RETURN_ORIGIN' for f in graph.facts)
