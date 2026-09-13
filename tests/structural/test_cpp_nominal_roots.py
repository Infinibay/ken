import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

@pytest.mark.parametrize('case',['chain','missing','cycle','diamond','multiple'])
def test_explicit_cpp_root_topologies(case):
    sources={
      'chain':'class A{};class B:public A{};class C:public B{};',
      'missing':'class A:public External{};class C:public A{};',
      'cycle':'class A:public C{};class C:public A{};',
      'diamond':'class A{};class B:virtual public A{};class D:virtual public A{};class C:public B,public D{};',
      'multiple':'class A{};class B{};class C:public A,public B{};',
    }
    graph=link_project([lower_source(sources[case],'cpp','roots.cpp')]);assert not graph.diagnostics
    roots={graph.entities[f.subject].name:graph.entities[f.object].name for f in graph.facts if f.relation=='NOMINAL_ROOT'}
    assert ('C' in roots)==(case in {'chain','diamond'})
    if 'C' in roots:assert roots['C']=='A'
