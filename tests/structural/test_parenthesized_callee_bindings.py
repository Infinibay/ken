"""Parentheses preserve a called binding without erasing other expressions."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR


LANGUAGES=['python','javascript','typescript','go','csharp','cpp','rust']


def source(language,callee='callback',array=False):
    name='callbacks' if array else 'callback'
    if language=='python':return f'def invoke({name},value):\n return {callee}(value)\n'
    if language=='javascript':return f'function invoke({name},value){{return {callee}(value);}}'
    if language=='typescript':return f'function invoke({name}: '+('Array<(value:number)=>number>' if array else '(value:number)=>number')+f',value:number){{return {callee}(value);}}'
    if language=='go':return f'package p;func invoke({name} '+('[]' if array else '')+f'func(int)int,value int)int{{return {callee}(value)}}'
    if language=='csharp':return 'using System;class C{int invoke(Func<int,int>'+('[]' if array else '')+f' {name},int value){{return {callee}(value);}}}}'
    if language=='cpp':return 'int invoke(int('+('**' if array else '*')+f'{name})(int),int value){{return {callee}(value);}}'
    return f'fn invoke({name}: '+('[fn(i32)->i32;1]' if array else 'fn(i32)->i32')+f',value:i32)->i32{{{callee}(value)}}'


def graph(text,language):
    result=IR.from_dict(link_project([lower_source(text,language,'callee')]).to_dict())
    assert not result.diagnostics
    return result


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('depth',[0,1,2,4])
def test_parenthesis_syntax_controls_binding_projection(language,depth):
    callee='('*depth+'callback'+')'*depth
    g=graph(source(language,callee),language)
    parameter=next(e.id for e in g.entities.values() if e.name=='callback' and e.kind=='PARAMETER')
    calls=[e.id for e in g.entities.values() if e.kind=='CALL']
    if language=='csharp' and depth==1:
        # C# resolves (identifier)(expression) as cast syntax, before name binding.
        assert not calls and any(o.native_kind=='cast_expression' for o in g.operations)
        return
    assert len(calls)==1
    assert any(f.subject==calls[0] and f.relation=='CALLEE_VALUE' and f.object==parameter for f in g.facts)
    assert not any(f.subject==calls[0] and f.relation=='INVOKES_RESULT_OF' for f in g.facts)
    if depth:assert any(o.native_kind=='parenthesized_expression' for o in g.operations)


@pytest.mark.parametrize('language',LANGUAGES)
def test_comments_inside_parentheses_do_not_erase_binding(language):
    callee='(\n # supplied function\n callback\n)' if language=='python' else '((/* supplied function */callback))'
    g=graph(source(language,callee),language)
    parameter=next(e.id for e in g.entities.values() if e.name=='callback' and e.kind=='PARAMETER')
    assert any(f.relation=='CALLEE_VALUE' and f.object==parameter for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('wrapped',[False,True])
def test_indexed_callee_keeps_its_own_container(language,wrapped):
    callee='((callbacks[0]))' if wrapped else 'callbacks[0]'
    g=graph(source(language,callee,array=True),language)
    bindings=[f.object for f in g.facts if f.relation=='CALLEE_VALUE']
    assert len(bindings)==1
    parameter=next(e.id for e in g.entities.values() if e.name=='callbacks' and e.kind=='PARAMETER')
    assert any(f.subject==bindings[0] and f.relation=='CONTAINER' and f.object==parameter for f in g.facts)
    assert any(f.subject==bindings[0] and f.relation=='INDEX' for f in g.facts)


def test_csharp_single_parenthesized_index_parser_gap_does_not_invent_a_call():
    # The grammar currently classifies this as cast/array-type syntax. Preserve
    # that limitation; do not generalize callee unwrapping to arbitrary casts.
    g=graph(source('csharp','(callbacks[0])',array=True),'csharp')
    assert any(o.native_kind=='cast_expression' for o in g.operations)
    assert not any(f.relation=='CALLEE_VALUE' for f in g.facts)


@pytest.mark.parametrize('language,callee',[
 ('python','(callback if value else None)'),
 ('python','(callback,)'),
 ('javascript','(0,callback)'),
 ('typescript','(value ? callback : undefined)'),
 ('cpp','(*callback)'),
 ('csharp','((Func<int,int>)callback)'),
 ('rust','(callback as fn(i32)->i32)'),
])
def test_other_expressions_do_not_claim_the_parameter_is_the_callee(language,callee):
    g=graph(source(language,callee),language)
    parameter=next(e.id for e in g.entities.values() if e.name=='callback' and e.kind=='PARAMETER')
    assert not any(f.relation=='CALLEE_VALUE' and f.object==parameter for f in g.facts)


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_inner_parameter_shadowing_is_preserved(language):
    text='def outer(callback):\n def inner(callback,value): return (callback)(value)\n return inner\n' if language=='python' else 'function outer(callback){function inner(callback,value){return (callback)(value);}return inner;}'
    g=graph(text,language)
    inner=next(e.id for e in g.entities.values() if e.name=='inner' and e.kind=='CALLABLE')
    parameters={f.object for f in g.facts if f.subject==inner and f.relation=='HAS_PARAMETER'}
    called=next(f.object for f in g.facts if f.relation=='CALLEE_VALUE')
    assert called in parameters and g.entities[called].name=='callback'
