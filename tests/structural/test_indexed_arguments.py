"""An argument's internal 'value' field is not an argument-wrapper field."""
import pytest
from ken.structural.frontend import lower_source


SOURCES = {
    'python': 'def f(table,key):\n consume(table[key])\n',
    'javascript': 'function f(table,key){consume(table[key]);}',
    'typescript': 'function f(table:any[],key:number){consume(table[key]);}',
    'java': 'class C{void f(Object[] table,int key){consume(table[key]);}}',
    'csharp': 'class C{void F(object[] table,int key){consume(table[key]);}}',
    'cpp': 'void f(int* table,int key){consume(table[key]);}',
    'go': 'package p;func f(table []int,key int){consume(table[key])}',
    'rust': 'fn f(table:Vec<i32>,key:usize){consume(table[key]);}',
}


@pytest.mark.parametrize('language', SOURCES)
def test_indexed_argument_retains_container_and_index(language):
    g = lower_source(SOURCES[language], language, 'sample')
    assert not g.diagnostics
    call = next(f.subject for f in g.facts if f.relation == 'CALLEE_NAME' and f.object == 'consume')
    argument = next(f.object for f in g.facts if f.subject == call and f.relation == 'ARGUMENT')
    container = next(f.object for f in g.facts if f.subject == argument and f.relation == 'CONTAINER')
    key = next(f.object for f in g.facts if f.subject == argument and f.relation == 'INDEX')
    assert g.entities[container].name == 'table'
    assert g.entities[key].name == 'key'
    assert argument != container


@pytest.mark.parametrize('spelling,kind', [('value=table[key]', 'named'),
                                          ('*table[key]', 'spread_positional'),
                                          ('**table[key]', 'spread_named')])
def test_python_wrappers_keep_indexed_expression(spelling, kind):
    g = lower_source(f'def f(table,key):\n consume({spelling})\n', 'python', 'sample')
    assert not g.diagnostics
    argument = next(f for f in g.facts if f.relation == 'ARGUMENT')
    assert argument.attrs['kind'] == kind
    assert any(f.subject == argument.object and f.relation == 'INDEX' for f in g.facts)


def test_csharp_named_argument_preserves_name_and_indexed_value():
    text = SOURCES['csharp'].replace('consume(table[key])', 'consume(value: table[key])')
    g = lower_source(text, 'csharp', 'sample')
    assert not g.diagnostics
    argument = next(f for f in g.facts if f.relation == 'ARGUMENT')
    assert argument.attrs['kind'] == 'named' and argument.attrs['name'] == 'value'
    assert any(f.subject == argument.object and f.relation == 'INDEX' for f in g.facts)
