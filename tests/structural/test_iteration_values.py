"""Iteration call origins and argument positions are reusable IR relationships."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


SOURCES = {
 'python':'def f():\n for item in getItems():\n  consume(0,item)\n',
 'javascript':'function f(){for(const item of getItems()){consume(0,item);}}',
 'typescript':'function f(){for(const item of getItems()){consume(0,item);}}',
 'java':'class C{void f(){for(Item item:getItems()){consume(0,item);}}}',
 'csharp':'class C{void f(){foreach(Item item in getItems()){consume(0,item);}}}',
 'cpp':'void f(){for(auto item:getItems()){consume(0,item);}}',
 'go':'package p;func f(){for _,item:=range getItems(){consume(0,item)}}',
 'rust':'fn f(){for item in getItems(){consume(0,item);}}',
}


@pytest.mark.parametrize('language',SOURCES)
def test_iteration_passes_element_at_exact_argument_position(language):
    graph=link_project([lower_source(SOURCES[language],language,'sample')])
    assert not graph.diagnostics
    passed=[f for f in graph.facts if f.relation=='ITERATION_PASSES_VALUE']
    origins=[f for f in graph.facts if f.relation=='ITERATION_ORIGIN']
    assert len(passed)==len(origins)==1
    assert passed[0].subject==origins[0].subject
    assert passed[0].attrs['position']==1
    assert graph.entities[passed[0].object].attrs['name']=='consume'
    assert graph.entities[origins[0].object].attrs['name']=='getItems'
    assert not any(f.relation=='ITERATION_SNAPSHOT'for f in graph.facts)


@pytest.mark.parametrize('language',SOURCES)
def test_passing_other_value_does_not_become_iteration_item_flow(language):
    text=SOURCES[language].replace('consume(0,item)','consume(0,other)')
    graph=link_project([lower_source(text,language,'sample')])
    assert not graph.diagnostics
    assert not any(f.relation=='ITERATION_PASSES_VALUE'for f in graph.facts)
