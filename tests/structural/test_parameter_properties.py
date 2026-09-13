"""Constructor parameters and fields retain separate source identities."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.kenql import query_graph
from ken.structural.rules import execute_rules, SavedRule


def analyze(source):
    graph = link_project([lower_source(source, 'typescript', 'parameters.ts')])
    assert not graph.diagnostics
    return graph


@pytest.mark.parametrize('modifier', ['public', 'private', 'protected', 'readonly', 'public readonly', 'private readonly', 'protected readonly'])
@pytest.mark.parametrize('suffix', ['', ' = new Context()'])
def test_parameter_properties_declare_distinct_typed_fields(modifier, suffix):
    graph = analyze(f'class Context {{}} class Holder {{ constructor({modifier} ctx: Context{suffix}) {{}} }}')
    edges = [f for f in graph.facts if f.relation == 'PARAMETER_INITIALIZES_FIELD']
    assert len(edges) == 1
    f = edges[0]
    assert graph.entities[f.subject].kind == 'PARAMETER'
    assert graph.entities[f.object].kind == 'STORAGE'
    assert f.subject != f.object
    assert graph.entities[f.subject].name == graph.entities[f.object].name == 'ctx'
    assert graph.entities[f.object].attrs['parameter_property']
    assert graph.entities[f.object].attrs['readonly'] == ('readonly' in modifier)
    types = {e.subject: e.object for e in graph.facts if e.relation == 'TYPE'}
    assert types[f.subject] == types[f.object]
    assert any(e.relation == 'CONSTRUCTOR_FIELD_INPUT' and e.subject == f.object and e.object == f.subject for e in graph.facts)


@pytest.mark.parametrize('declaration', [
    'constructor(ctx: Context) {}',
    'constructor(/* public */ ctx: Context) {}',
    'constructor(ctx = "public readonly") {}',
    'method(public ctx: Context) {}',
    'constructor(public ctx: Context);',
])
def test_plain_parameters_comments_defaults_and_signatures_are_not_properties(declaration):
    graph = analyze('class Context {} class Holder { '+declaration+' }')
    assert not any(f.relation == 'PARAMETER_INITIALIZES_FIELD' for f in graph.facts)


@pytest.mark.parametrize('body,expected', [
    ('', True), ('const other = 1;', True),
    ('ctx = null;', False), ('this.ctx = null;', False),
    ('this.ctx = ctx; this.ctx = null;', False),
    ('this.ctx = null; this.ctx = ctx;', True),
    ('if (ctx) { this.ctx = ctx; }', False),
    ('this.ctx += ctx;', False),
    ('consume(this);', False),
    ('const alias = this;', False),
    ('consume([this]);', False),
])
def test_property_initialization_is_not_a_final_input_after_overwrite_or_escape(body, expected):
    graph = analyze('class Context {} class Holder { constructor(public ctx: Context) {'+body+'} }')
    assert any(f.relation == 'PARAMETER_INITIALIZES_FIELD' for f in graph.facts)
    assert any(f.relation == 'CONSTRUCTOR_FIELD_INPUT' for f in graph.facts) == expected


def test_implicit_assignment_is_not_invented_as_an_ast_statement():
    graph = analyze('class Context {} class Holder { constructor(public ctx: Context) {} }')
    assert not any(o.kind == 'ASSIGN' for o in graph.operations)
    assert not any(f.relation == 'ASSIGNMENT_TARGET' for f in graph.facts)
    q = '''query fields {
      require $parameter PARAMETER_INITIALIZES_FIELD $field;
      require $field CONSTRUCTOR_FIELD_INPUT $parameter;
      emit $parameter, $field;
    }'''
    out = execute_rules(graph, [SavedRule('properties', q)])
    assert out['complete'] and len(out['matches']) == 1
    view = query_graph(graph).ir
    assert query_graph(IR.from_dict(view.to_dict())).ir.to_dict() == view.to_dict()
