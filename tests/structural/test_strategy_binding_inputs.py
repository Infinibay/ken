"""Source-level policy contrasts: last writes, nominal slots and public roles."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import SavedRule,builtin_rules,named_rule,execute_rules
from ken.structural.query import QueryBudget


OBJECT_LANGUAGES=['python','typescript','java','csharp','cpp']
CALLABLE_LANGUAGES=['python','javascript','typescript','go']
CHANGES=['positive','renamed','overwrite-before','overwrite-after','rebind-before',
         'rebind-after','return-before','return-after','wrong-field','no-call',
         'same-method','other-parameter-final']
POSITIVE={'positive','renamed','overwrite-before','return-after','other-parameter-final'}


def source(language,kind='object',change='positive'):
    py=language=='python';go=language=='go';cpp=language=='cpp';ts=language=='typescript'
    prefix='self.' if py else 'c.' if go else '' if cpp else 'this.'
    null='None' if py else 'nil' if go else 'nullptr' if cpp else 'null'
    field=prefix+'policy';store=field+'=supplied';terminator='' if py else ';'
    lines=[store]
    if change=='overwrite-before':lines=[field+'='+null,store]
    if change=='overwrite-after':lines=[store,field+'='+null]
    if change=='rebind-before':lines=['supplied='+null,store]
    if change=='rebind-after':lines=[store,'supplied='+null]
    if change=='return-before':lines=['return',store]
    if change=='return-after':lines=[store,'return',field+'='+null]
    if change=='wrong-field':lines=[prefix+'other=supplied']
    if change=='other-parameter-final':lines=[store,field+'=replacement']
    access='missing' if change=='missing-slot' else 'run'
    call=field+'(value)' if kind=='callable' else field+('->' if cpp else '.')+access+'(value)'
    apply_body='return '+call if change!='no-call' else 'return value'
    if change=='same-method':lines.append((field+'(1)') if kind=='callable' else field+('->' if cpp else '.')+'run(1)');apply_body='return value'
    if change=='branch':lines=[store,('if flag: '+field+'='+null) if py else 'if flag { '+field+'='+null+'; }' if go else 'if(flag){'+field+'='+null+';}']
    if change=='loop':lines=[('while flag: '+store) if py else 'for flag { '+store+'; }' if go else 'while(flag){'+store+';}']
    if py:
        body='\n'.join('  '+line for line in lines)
        contract='''class Contract:
 def run(self,value): return value
class First(Contract):
 def run(self,value): return value+1
class Second(Contract):
 def run(self,value): return value+2
''' if kind=='object' else ''
        annotation=':Contract' if kind=='object' else ''
        fields=' policy:Contract\n other:Contract\n' if kind=='object' else ''
        text=contract+'class Context:\n'+fields+f' def configure(self,supplied{annotation},replacement{annotation},flag=False):\n{body}\n def apply(self,value): {apply_body}\n'
    else:
        body=''.join(line+terminator for line in lines)
        if go:
            text='package sample; type Context struct{policy func(int)int;other func(int)int};func(c *Context)configure(supplied func(int)int,replacement func(int)int,flag bool){'+body+'};func(c *Context)apply(value int)int{'+apply_body+'}'
        elif language=='javascript':
            text='class Context{configure(supplied,replacement,flag){'+body+'}apply(value){'+apply_body+'}}'
        elif ts:
            contract='interface Contract{run(value:number):number;}class First implements Contract{run(value:number){return value+1;}}class Second implements Contract{run(value:number){return value+2;}}' if kind=='object' else ''
            typ='Contract' if kind=='object' else '(value:number)=>number'
            text=contract+f'class Context{{policy:{typ};other:{typ};configure(supplied:{typ},replacement:{typ},flag:boolean){{{body}}}apply(value:number){{{apply_body}}}}}'
        elif cpp:
            text='class Contract{public:virtual int run(int value){return value;}};class First:public Contract{public:int run(int value){return value+1;}};class Second:public Contract{public:int run(int value){return value+2;}};class Context{Contract*policy;Contract*other;public:void configure(Contract*supplied,Contract*replacement,bool flag){'+body+'}int apply(int value){'+apply_body+';}};'
        else:
            inheritance='implements' if language=='java' else ':'
            contract='interface Contract{int run(int value);}'
            text=contract+f'class First {inheritance} Contract{{public int run(int value){{return value+1;}}}}class Second {inheritance} Contract{{public int run(int value){{return value+2;}}}}class Context{{Contract policy;Contract other;public void configure(Contract supplied,Contract replacement,bool flag){{{body}}}public int apply(int value){{{apply_body};}}}}'
            if language=='java':text=text.replace('bool flag','boolean flag')
    if change=='renamed':
        for old,new in [('Context','Pricing'),('Contract','Extension'),('policy','discount'),('run','calculate')]:text=re.sub(r'\b'+old+r'\b',new,text)
    return text


def graph_and_result(text,language,query='strategy'):
    graph=link_project([lower_source(text,language,'policy-example')]);assert not graph.diagnostics
    rules=builtin_rules();rule=named_rule(query,rules) if isinstance(query,str) else query
    out=execute_rules(graph,[rule],registry=rules);assert out['complete']
    return graph,out


@pytest.mark.parametrize('language',OBJECT_LANGUAGES)
@pytest.mark.parametrize('change',CHANGES+['missing-slot'])
def test_object_policy_last_write_and_contract_slot(language,change):
    _,out=graph_and_result(source(language,'object',change),language)
    assert bool(out['matches'])==(change in POSITIVE)


@pytest.mark.parametrize('language',CALLABLE_LANGUAGES)
@pytest.mark.parametrize('change',CHANGES)
def test_callable_policy_last_write(language,change):
    _,out=graph_and_result(source(language,'callable',change),language)
    assert bool(out['matches'])==(change in POSITIVE)


@pytest.mark.parametrize('kind,languages',[('object',OBJECT_LANGUAGES),('callable',CALLABLE_LANGUAGES)])
@pytest.mark.parametrize('change',['branch','loop'])
def test_unmodeled_configuration_is_explicitly_unsupported(kind,languages,change):
    for language in languages:
        graph,out=graph_and_result(source(language,kind,change),language)
        assert not out['matches']
        configure=next(e.id for e in graph.entities.values() if e.name=='configure')
        assert any(f.subject==configure and f.relation=='BINDING_FLOW_STATUS' and f.object=='unsupported' for f in graph.facts)


@pytest.mark.parametrize('language',OBJECT_LANGUAGES)
def test_public_operation_preserves_final_input_role_without_requiring_dispatch(language):
    query=SavedRule('usage','''query usage {
      match "strategy.supplied_policy"(unit:$unit,configure:$configure,supplied:$input,policy:$field);
      emit $unit,$configure,$input,$field;
    }''')
    graph,out=graph_and_result(source(language,change='other-parameter-final'),language,query)
    assert len(out['matches'])==1
    assert graph.entities[out['matches'][0]['bindings']['$input']].name=='replacement'
    _,out=graph_and_result(source(language,change='no-call'),language,query)
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',OBJECT_LANGUAGES)
def test_another_field_cannot_supply_the_invoked_policy(language):
    text=source(language,change='wrong-field')
    _,out=graph_and_result(text,language)
    assert not out['matches']


@pytest.mark.parametrize('default',['None','Descriptor()'])
@pytest.mark.parametrize('change',['positive','overwrite-after','rebind-before','overwrite-before'])
def test_python_class_binding_is_source_write_not_descriptor_storage(default,change):
    text='class Descriptor:\n def __get__(self,obj,owner): return lambda value: value\n def __set__(self,obj,value): pass\n'
    text+=source('python','callable',change).replace('class Context:\n','class Context:\n policy='+default+'\n')
    graph,out=graph_and_result(text,'python')
    assert bool(out['matches'])==(change in POSITIVE)
    field=next(e.id for e in graph.entities.values() if e.name=='policy' and e.kind=='STORAGE')
    assert graph.entities[field].attrs['static']
    writes={f.subject for f in graph.facts if f.relation=='ASSIGNMENT_TARGET' and f.object==field}
    assert not any(f.subject in writes and f.relation=='FINAL_MEMBER_INPUT' for f in graph.facts)


@pytest.mark.parametrize('language',['python','typescript','java','csharp'])
def test_declared_slot_remains_usable_with_multiple_possible_runtime_targets(language):
    text=source(language)
    if language=='python':text+=' def seed(self): self.policy=First()\n'
    else:
        extra='seed(){this.policy=new First();}' if language=='typescript' else 'public void seed(){this.policy=new First();}'
        text=text[:-1]+extra+'}'
    graph,out=graph_and_result(text,language)
    assert out['matches']
    policy=next(e.id for e in graph.entities.values() if e.name=='policy' and e.kind=='STORAGE')
    calls={f.subject for f in graph.facts if f.relation=='RECEIVER' and f.object==policy}
    assert any(f.subject in calls and f.relation=='DECLARED_TARGET' for f in graph.facts)
    assert any(f.subject in calls and f.relation=='MAY_TARGET' for f in graph.facts)


@pytest.mark.parametrize('language',['typescript','cpp'])
@pytest.mark.parametrize('change',['positive','overwritten','rebound','unused','wrong-field'])
def test_constructor_initialization_supplies_policy_without_an_assignment_node(language,change):
    prefix=source(language).split('class Context{')[0]
    field='other' if change=='wrong-field' else 'policy'
    if language=='cpp':
        body='policy=nullptr;' if change=='overwritten' else 'supplied=nullptr;' if change=='rebound' else ''
        call='value' if change=='unused' else 'policy->run(value)'
        text=prefix+f'class Context{{Contract*policy;Contract*other;public:Context(Contract*supplied):{field}{{supplied}}{{{body}}}int apply(int value){{return {call};}}}};'
    else:
        body='this.policy=null;' if change=='overwritten' else f'{field}=null;' if change=='rebound' else ''
        call='value' if change=='unused' else 'this.policy.run(value)'
        extra='policy:Contract;' if change=='wrong-field' else ''
        text=prefix+f'class Context{{{extra}constructor(public {field}:Contract){{{body}}}apply(value:number){{return {call};}}}}'
    graph,out=graph_and_result(text,language)
    assert bool(out['matches'])==(change=='positive')
    if change=='positive':assert any(f.relation=='CONSTRUCTOR_FIELD_INPUT' for f in graph.facts)


def test_many_fields_and_parameters_do_not_form_a_cartesian_product_before_writes():
    text=''.join(f'class Context{i}:\n'+''.join(f' policy{j}:object\n' for j in range(8))
                 +' def configure(self,supplied,'+','.join(f'p{j}' for j in range(7))
                 +'): self.policy0=supplied\n def apply(self,value): return self.policy0(value)\n'
                 for i in range(120))
    graph=link_project([lower_source(text,'python','many.py')]);assert not graph.diagnostics
    rules=builtin_rules()
    out=execute_rules(graph,[named_rule('strategy',rules)],
                      QueryBudget(max_matches=500,max_states=10000),registry=rules)
    assert out['complete'] and len(out['matches'])==120
