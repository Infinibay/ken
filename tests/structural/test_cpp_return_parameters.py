"""Return declarator wrappers do not erase a C++ callable's formal parameters."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.kenql import query_graph


@pytest.mark.parametrize('result',['Product','Product *','Product **','Product &','const Product *','Product &&'])
@pytest.mark.parametrize('method',[False,True])
def test_parameters_under_return_declarators(result,method):
    declaration=f'{result} make(int value, const Product &source) {{ consume(value,source); }}'
    source='class Product {}; '+('class Factory {public: '+declaration+'};' if method else declaration)
    graph=link_project([lower_source(source,'cpp','declarator.cpp')]);assert not graph.diagnostics
    fn=next(e for e in graph.entities.values() if e.kind=='CALLABLE' and e.name=='make')
    parameters=[graph.entities[f.object] for f in graph.facts if f.relation=='HAS_PARAMETER' and f.subject==fn.id and not f.attrs.get('receiver')]
    assert [p.name for p in parameters]==['value','source']
    assert next(f.attrs['arity'] for f in query_graph(graph).rows('ENTITY',fn.id))==2
    assert [p.attrs['position'] for p in parameters]==[0,1]
    # Operands reference the formal bindings, not synthetic locals of the same name.
    operands={f.object for f in graph.facts if f.relation=='ARGUMENT'}
    assert {p.id for p in parameters}<=operands


def test_callback_parameter_list_does_not_replace_enclosing_formals():
    source='class Product{}; Product *make(int value, void (*callback)(int nested)) { callback(value); }'
    graph=link_project([lower_source(source,'cpp','callback.cpp')]);assert not graph.diagnostics
    fn=next(e for e in graph.entities.values() if e.kind=='CALLABLE' and e.name=='make')
    ps=[graph.entities[f.object] for f in graph.facts if f.relation=='HAS_PARAMETER' and f.subject==fn.id]
    assert len(ps)==2
    assert ps[0].name=='value'
    assert all(p.name!='nested' for p in ps)
