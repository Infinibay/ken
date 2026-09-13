"""Injected functions across language-specific callable spellings."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule


SOURCES={
 'python':'class Consumer:\n def configure(self,incoming,replacement): self.dependency=incoming\n def handle(self,value): return self.dependency(value)\n',
 'javascript':'class Consumer{configure(incoming,replacement){this.dependency=incoming;}handle(value){return this.dependency(value);}}',
 'typescript':'class Consumer{dependency:(value:number)=>number;configure(incoming:(value:number)=>number,replacement:(value:number)=>number){this.dependency=incoming;}handle(value:number){return this.dependency(value);}}',
 'go':'package p;type Consumer struct{dependency func(int)int};func(c *Consumer)configure(incoming func(int)int,replacement func(int)int){c.dependency=incoming};func(c *Consumer)handle(value int)int{return c.dependency(value)}',
 'csharp':'using System;class Consumer{Func<int,int> dependency;void configure(Func<int,int> incoming,Func<int,int> replacement){this.dependency=incoming;}int handle(int value){return this.dependency(value);}}',
 'cpp':'class Consumer{int(*dependency)(int);public:void configure(int(*incoming)(int),int(*replacement)(int)){dependency=incoming;}int handle(int value){return dependency(value);}};',
 'rust':'struct Consumer{dependency:fn(i32)->i32}impl Consumer{fn configure(&mut self,mut incoming:fn(i32)->i32,replacement:fn(i32)->i32){self.dependency=incoming;}fn handle(&self,value:i32)->i32{(self.dependency)(value)}}',
}
CHANGES=['positive','renamed','parentheses','prior-write','overwrite','input-before','input-after',
         'return-before','dead-write','replacement','wrong-field','no-call','no-input','zero-arguments']
POSITIVES={'positive','renamed','parentheses','prior-write','dead-write','replacement','zero-arguments'}


def source(language,change='positive'):
    text=SOURCES[language]
    prefix='self.' if language in {'python','rust'} else 'c.' if language=='go' else '' if language=='cpp' else 'this.'
    field=prefix+'dependency';assignment=field+'=incoming'
    null='None' if language=='python' else 'nil' if language=='go' else 'nullptr' if language=='cpp' else 'fallback' if language=='rust' else 'null'
    replacement={
      'prior-write':field+'='+null+';'+assignment,
      'overwrite':assignment+';'+field+'='+null,
      'input-before':'incoming='+null+';'+assignment,
      'input-after':assignment+';incoming='+null,
      'return-before':'return;'+assignment,
      'dead-write':assignment+';return;'+field+'='+null,
      'replacement':assignment+';'+field+'=replacement',
      'no-input':field+'='+null,
    }.get(change,assignment)
    text=text.replace(assignment,replacement)
    call=f'({field})(value)' if language=='rust' else field+'(value)'
    if change=='parentheses':text=text.replace(call,'(( '+field+' ))(value)')
    if change=='wrong-field':text=text.replace(call,call.replace('dependency','other'))
    if change=='no-call':text=text.replace(call,'value')
    if change=='zero-arguments':
        text=text.replace(call,call.replace('(value)','()'))
        if language=='typescript':text=text.replace('(value:number)=>number','()=>number')
        if language=='cpp':text=text.replace(')(int)',')()')
        if language=='csharp':text=text.replace('Func<int,int>','Func<int>')
        if language=='rust':text=text.replace('fn(i32)->i32','fn()->i32')
        if language=='go':text=text.replace('func(int)int','func()int')
    if language=='rust' and 'fallback' in text:text+=' fn fallback(value:i32)->i32{value}'
    if change=='renamed':
        for old,new in [('Consumer','Endpoint'),('dependency','create_record'),('configure','wire'),('incoming','provider'),('handle','process')]:text=re.sub(r'\b'+old+r'\b',new,text)
    return text


def search(text,language,rule='architecture.dependency-injection'):
    graph=link_project([lower_source(text,language,'injection')]);assert not graph.diagnostics
    registry=builtin_rules();chosen=named_rule(rule,registry) if isinstance(rule,str) else rule
    out=execute_rules(graph,[chosen],registry=registry);assert out['complete']
    return graph,out


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('change',CHANGES)
def test_callable_input_and_near_misses(language,change):
    _,out=search(source(language,change),language)
    assert bool(out['matches'])==(change in POSITIVES)


@pytest.mark.parametrize('language',['python','javascript','typescript','csharp','cpp'])
def test_constructor_body_supplies_a_callable(language):
    text=source(language)
    if language=='python':text=text.replace('configure','__init__')
    elif language in {'javascript','typescript'}:text=text.replace('configure','constructor')
    else:text=text.replace('void configure','Consumer')
    _,out=search(text,language,'architecture.dependency-injection#callable-input')
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_async_consumer_still_uses_the_supplied_callable(language):
    text=source(language)
    if language=='python':text=text.replace('def handle','async def handle').replace('return self.dependency','return await self.dependency')
    else:text=text.replace('handle(value','async handle(value').replace('return this.dependency','return await this.dependency')
    _,out=search(text,language)
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_consumer_can_guard_an_optional_callable(language):
    text=source(language)
    if language=='python':text=text.replace('return self.dependency(value)','\n  if self.dependency:\n   return self.dependency(value)\n  return value')
    else:text=text.replace('return this.dependency(value);','if(this.dependency){return this.dependency(value);}return value;')
    _,out=search(text,language)
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_callable_configuration_with_a_branch_has_no_last_input_claim(language):
    text=source(language)
    if language=='python':text=text.replace('self.dependency=incoming','\n  if incoming: self.dependency=incoming')
    else:text=text.replace('this.dependency=incoming;','if(incoming){this.dependency=incoming;}')
    graph,out=search(text,language,'architecture.dependency-injection#callable-input')
    assert not out['matches']
    assert any(f.relation=='BINDING_FLOW_STATUS' and f.object=='unsupported' for f in graph.facts)


@pytest.mark.parametrize('change',['positive','overwritten'])
def test_python_descriptor_exposes_source_write_without_heap_identity(change):
    text='class Descriptor:\n def __get__(self,obj,owner): return lambda value:value\n def __set__(self,obj,value): pass\n'
    text+=source('python','overwrite' if change=='overwritten' else 'positive').replace('class Consumer:\n','class Consumer:\n dependency=Descriptor()\n')
    _,out=search(text,'python','architecture.dependency-injection#callable-input')
    assert bool(out['matches'])==(change=='positive')


def test_java_functional_interface_uses_the_object_variant():
    text='interface Converter{int apply(int value);}class Consumer{Converter dependency;Consumer(Converter incoming){this.dependency=incoming;}int handle(int value){return dependency.apply(value);}}'
    _,out=search(text,'java','architecture.dependency-injection#object-assignment')
    assert len(out['matches'])==1


def test_named_query_exports_keep_the_dependency_and_consumer_correlated():
    text=source('python')+'class Other:\n def configure(self,incoming): self.dependency=incoming\n def handle(self,value): return value\n'
    graph,out=search(text,'python',SavedRule('usage','''query usage {
      match "architecture.dependency-injection#callable-input"(unit:$unit,dependency:$field,inject:$configure,operation:$consumer);
      emit $unit,$field,$configure,$consumer;
    }'''))
    assert len(out['matches'])==1
    roles=out['matches'][0]['bindings']
    assert graph.entities[roles['$unit']].name=='Consumer'
    assert graph.entities[roles['$consumer']].name=='handle'


@pytest.mark.parametrize('language',SOURCES)
def test_locally_created_callable_is_not_a_supplied_dependency(language):
    local={
      'python':'(lambda value:value)', 'javascript':'(value=>value)',
      'typescript':'((value:number)=>value)', 'csharp':'(value=>value)',
      'cpp':'[](int value){return value;}', 'rust':'|value|value',
      'go':'func(value int)int{return value}',
    }[language]
    text=source(language).replace('dependency=incoming','dependency='+local)
    _,out=search(text,language)
    assert not out['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_configuration_and_consumption_must_be_distinct_methods(language):
    prefix='self.' if language in {'python','rust'} else 'c.' if language=='go' else '' if language=='cpp' else 'this.'
    call=f'({prefix}dependency)(value)' if language=='rust' else prefix+'dependency(value)'
    text=source(language).replace(call,'value')
    text=text.replace('dependency=incoming','dependency=incoming;'+call.replace('(value)','(1)'))
    _,out=search(text,language)
    assert not out['matches']


@pytest.mark.parametrize('language',['python','javascript','typescript','go'])
def test_supplied_callable_can_receive_expanded_arguments(language):
    text=source(language)
    if language=='python':text=text.replace('handle(self,value)','handle(self,*args,**kwargs)').replace('self.dependency(value)','self.dependency(*args,**kwargs)')
    elif language=='go':text=text.replace('func(int)int','func(...int)int').replace('handle(value int)','handle(values ...int)').replace('c.dependency(value)','c.dependency(values...)')
    else:
        if language=='typescript':text=text.replace('(value:number)=>number','(...values:number[])=>number').replace('handle(value:number)','handle(...values:number[])')
        else:text=text.replace('handle(value)','handle(...values)')
        text=text.replace('this.dependency(value)','this.dependency(...values)')
    _,out=search(text,language)
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',['python','javascript','typescript','java','csharp'])
def test_object_variant_preserves_conditional_injection_with_its_weaker_claim(language):
    from .test_modern_patterns import SOURCES as OBJECT_SOURCES
    text=OBJECT_SOURCES[language]
    if language=='python':text=text.replace('self.dependency = incoming','\n  if incoming is not None: self.dependency = incoming')
    else:text=text.replace('this.dependency = incoming;','if(incoming != null){this.dependency = incoming;}')
    _,out=search(text,language,'architecture.dependency-injection#object-assignment')
    assert len(out['matches'])==1


@pytest.mark.parametrize('change',['positive','parentheses','overwrite','wrong-field','replacement'])
def test_typescript_private_hash_field_keeps_its_identity(change):
    text=source('typescript',change).replace('dependency','#dependency')
    _,out=search(text,'typescript','architecture.dependency-injection#callable-input')
    assert bool(out['matches'])==(change in POSITIVES)


@pytest.mark.parametrize('change',['positive','overwritten','no-call','other-field'])
def test_typescript_function_parameter_property(change):
    field='other' if change=='other-field' else 'dependency'
    extra='dependency:(value:number)=>number;' if change=='other-field' else ''
    body='this.dependency=null;' if change=='overwritten' else ''
    result='value' if change=='no-call' else 'this.dependency(value)'
    text=f'class Consumer{{{extra}constructor(private {field}:(value:number)=>number){{{body}}}handle(value:number){{return {result};}}}}'
    _,out=search(text,'typescript','architecture.dependency-injection#callable-input')
    assert bool(out['matches'])==(change=='positive')
