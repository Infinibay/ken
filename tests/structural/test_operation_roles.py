"""Source field roles can distinguish condition evaluation from branch bodies."""
import pytest

from ken.structural import lower_source, link_project
from ken.structural.kenql import Engine, parse, query_graph


SOURCES = {
    'python':'def f(x):\n if probe(x):\n  yes()\n else:\n  no()\n',
    'javascript':'function f(x){if(probe(x)){yes();}else{no();}}',
    'typescript':'function f(x:number){if(probe(x)){yes();}else{no();}}',
    'java':'class C{void f(int x){if(probe(x)){yes();}else{no();}}}',
    'csharp':'class C{void f(int x){if(probe(x)){yes();}else{no();}}}',
}


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('role', ['condition','consequence','alternative'])
def test_operation_role_selector_preserves_source_fields(language, role):
    graph = link_project([lower_source(SOURCES[language],language,'sample')])
    assert not graph.diagnostics
    facts = [f for f in graph.facts if f.relation=='OPERATION' and f.attrs.get('role')==role]
    assert facts
    for fact in facts:
        op = next(o for o in graph.operations if o.id==fact.subject)
        assert op.role == role
    query=parse(f'query role {{ operation(role: "{role}") as $op; emit $op; }}')
    result=Engine(query_graph(graph),{}).execute(query)
    assert result['complete']
    assert {m['bindings']['$op'] for m in result['matches']} == {f.subject for f in facts}


def test_role_is_not_silently_accepted_on_callable_selectors():
    with pytest.raises(ValueError,match='unknown selector'):
        parse('query bad { callable(role: condition) as $f; emit $f; }')
