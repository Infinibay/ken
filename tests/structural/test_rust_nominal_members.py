"""Rust annotation heads and initializer fields retain their source evidence."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule, builtin_rules, execute_rules


def analyze(source):
    graph=link_project([lower_source(source,'rust','nominal.rs')])
    assert not graph.diagnostics
    return IR.from_dict(graph.to_dict())


def facts(graph,relation,subject=None):
    return [f for f in graph.facts if f.relation==relation and (subject is None or f.subject==subject)]


@pytest.mark.parametrize('annotation',[
 "Product<'a>", "&'a Product<'a>", "&'a mut Product<'a>",
 "*const Product<'a>", "*mut Product<'a>", "&&Product<'a>",
])
def test_nominal_annotation_links_without_erasing_lifetime_or_wrapper(annotation):
    graph=analyze("struct Product<'a>{value:&'a str} fn f<'a>(value:"+annotation+"){}")
    parameter=next(e for e in graph.entities.values() if e.kind=='PARAMETER' and e.name=='value')
    product=next(e for e in graph.entities.values() if e.kind=='CLASS' and e.name=='Product')
    assert [f.object for f in facts(graph,'TYPE_HEAD',parameter.id)]==['Product']
    assert [f.object for f in facts(graph,'TYPE',parameter.id)]==[product.id]
    assert [f.object for f in facts(graph,'TYPE_NAME',parameter.id)]==[annotation]
    assert parameter.attrs['native_type']==annotation
    assert facts(graph,'TYPE_REF',parameter.id)


@pytest.mark.parametrize('annotation',["external::Product<'a>","&external::Product<'a>","[Product<'a>; 3]","(Product<'a>,)"])
def test_paths_and_containers_are_not_reduced_to_a_local_basename(annotation):
    graph=analyze("struct Product<'a>{value:&'a str} fn f<'a>(value:"+annotation+"){}")
    parameter=next(e for e in graph.entities.values() if e.kind=='PARAMETER' and e.name=='value')
    assert not facts(graph,'TYPE_HEAD',parameter.id)
    assert not facts(graph,'TYPE',parameter.id)
    assert facts(graph,'TYPE_REF',parameter.id)


@pytest.mark.parametrize('body',[
 'struct Holder<T>{value:T}',
 'fn f<T>(value:T){}',
 'struct Holder<T>{value:T} impl<T> Holder<T>{fn f(&self,value:T){}}',
 'struct Holder{} impl Holder{fn f<T>(&self,value:T){}}',
 'fn f<T>(value:&T){}',
])
def test_bound_generic_does_not_bind_to_global_homonym(body):
    graph=analyze('struct T{} '+body)
    subjects={f.subject for f in facts(graph,'TYPE_HEAD') if f.object=='T'}
    assert subjects
    assert not [f for f in facts(graph,'TYPE') if f.subject in subjects]


@pytest.mark.parametrize('shorthand',[False,True])
@pytest.mark.parametrize('attribute',['','#[cfg(feature="x")] ','#[cfg(feature="x")] /* between */ ','#[allow(unused)]\n// between\n'])
def test_initializer_fields_and_modalities_survive_linking(shorthand,attribute):
    expr='value' if shorthand else 'value:value'
    graph=analyze('struct Product{value:i32,other:i32} fn f(value:i32,old:Product){Product{'+attribute+expr+',..old};}')
    initializers=facts(graph,'HAS_INITIALIZER');assert len(initializers)==1
    initializer=initializers[0].object
    assert initializer in {op.id for op in graph.operations}
    assert [f.object for f in facts(graph,'FIELD_NAME',initializer)]==['value']
    field=facts(graph,'INITIALIZES_FIELD',initializer);assert len(field)==1
    assert graph.entities[field[0].object].name=='value'
    stores=facts(graph,'STORES_VALUE',initializer);assert len(stores)==1
    assert graph.entities[stores[0].object].kind=='PARAMETER'
    for f in [*initializers,*field,*stores,*facts(graph,'FIELD_NAME',initializer)]:
        assert f.attrs.get('modality')==('may' if attribute else None)
    # The struct update does not invent an initialization for `other`.
    assert len(facts(graph,'INITIALIZES_FIELD'))==1


def test_derived_copy_operation_correlates_public_roles_after_roundtrip():
    graph=analyze('''#[derive(Clone)] struct Product{value:i32}
fn f(value:Product,other:Product){let x=value.clone();let y=other.clone();}''')
    query='''query q {
      parameter(name: "value") as $receiver;
      match "prototype.derived_copy"(unit:$unit,receiver:$receiver,copy:$copy);
      emit $unit,$receiver,$copy;
    }'''
    result=execute_rules(graph,[SavedRule('copy-use',query)],registry=builtin_rules())
    assert result['complete'] and len(result['matches'])==1,result
    bindings=result['matches'][0]['bindings']
    assert graph.entities[bindings['$unit']].name=='Product'
    assert graph.entities[bindings['$receiver']].name=='value'
