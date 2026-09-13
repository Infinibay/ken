"""Last source binding writes are distinct from member/heap retention."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


LANGUAGES=['python','javascript','typescript','java','csharp','cpp','go','rust']
CASES=['positive','prior-write','overwrite','rebind-before','rebind-after',
       'return-before','dead-write','replacement','alias','branch','loop']


def source(language,case):
    sep='\n ' if language=='python' else ';'
    assign='saved=supplied'
    lines={
      'positive':[assign], 'prior-write':['saved=0',assign],
      'overwrite':[assign,'saved=0'], 'rebind-before':['supplied=0',assign],
      'rebind-after':[assign,'supplied=0'], 'return-before':['return',assign],
      'dead-write':[assign,'return','saved=0'], 'replacement':[assign,'saved=replacement'],
      'alias':['temporary=supplied','saved=temporary'],
      'branch':['if supplied: '+assign] if language=='python' else ['if supplied>0 {'+assign+'; }'] if language in {'go','rust'} else ['if(supplied>0){'+assign+'; }'],
      'loop':['while supplied: '+assign] if language=='python' else ['for supplied>0 {'+assign+'; }'] if language=='go' else ['while supplied>0 {'+assign+'; }'] if language=='rust' else ['while(supplied>0){'+assign+'; }'],
    }[case]
    body=sep.join(lines)+('' if language=='python' else ';')
    if language=='python':return 'def retain(supplied,replacement):\n '+body+'\n'
    if language=='javascript':return 'function retain(supplied,replacement){let saved;let temporary;'+body+'}'
    if language=='typescript':return 'function retain(supplied:number,replacement:number){let saved:number;let temporary:number;'+body+'}'
    if language in {'java','csharp'}:return 'class Bindings{static void retain(int supplied,int replacement){int saved=0;int temporary=0;'+body+'}}'
    if language=='cpp':return 'void retain(int supplied,int replacement){int saved=0;int temporary=0;'+body+'}'
    if language=='go':return 'package p;func retain(supplied int,replacement int){var saved int;var temporary int;'+body+'}'
    return 'fn retain(mut supplied:i32,replacement:i32){let mut saved=0;let mut temporary=0;'+body+'}'


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_local_last_binding_input(language,case):
    graph=IR.from_dict(link_project([lower_source(source(language,case),language,'bindings')]).to_dict())
    assert not graph.diagnostics
    result=execute_rules(graph,[SavedRule('binding','''query binding {
      variable(name:"saved") as $binding;
      require $write ASSIGNMENT_TARGET $binding;
      require $write FINAL_BINDING_INPUT $input [basis:linear-syntax,analysis:"linear-bindings/1"];
      emit $binding,$write,$input;
    }''')]);assert result['complete']
    expected=case in {'positive','prior-write','dead-write','replacement'}
    assert bool(result['matches'])==expected,(language,case,result)
    if expected:
        assert len(result['matches'])==1
        input_id=result['matches'][0]['bindings']['$input']
        assert graph.entities[input_id].name==('replacement' if case=='replacement' else 'supplied')
    assert not any(f.relation in {'FINAL_MEMBER_INPUT','MEMBER_FLOW_STATUS'} for f in graph.facts)
    states=[f for f in graph.facts if f.relation=='BINDING_FLOW_STATUS']
    assert len(states)==1 and states[0].object==('unsupported' if case in {'branch','loop'} else 'supported')


@pytest.mark.parametrize('language',['python','javascript','typescript','java','csharp','cpp'])
@pytest.mark.parametrize('overwritten',[False,True])
def test_static_binding_write_does_not_become_instance_member_input(language,overwritten):
    end=';value=0' if overwritten else ''
    sources={
     'python':'class C:\n value=0\n def set(self,supplied): self.value=supplied'+(';self.value=0' if overwritten else '')+'\n',
     'javascript':'class C{static value=0;static set(supplied){this.value=supplied'+(';this.value=0' if overwritten else '')+';}}',
     'typescript':'class C{static value:number=0;static set(supplied:number){this.value=supplied'+(';this.value=0' if overwritten else '')+';}}',
     'java':'class C{static int value;static void set(int supplied){value=supplied'+end+';}}',
     'csharp':'class C{static int value;static void set(int supplied){value=supplied'+end+';}}',
     'cpp':'class C{static int value;static void set(int supplied){value=supplied'+end+';}};',
    }
    graph=link_project([lower_source(sources[language],language,'static')]);assert not graph.diagnostics
    assert bool([f for f in graph.facts if f.relation=='FINAL_BINDING_INPUT']) is (not overwritten)
    assert not any(f.relation=='FINAL_MEMBER_INPUT' for f in graph.facts)


def test_variadic_parameters_are_direct_values_without_expansion_claim():
    graph=link_project([lower_source('def retain(*args,**kwargs):\n values=args\n options=kwargs\n','python','variadic.py')])
    inputs=[f for f in graph.facts if f.relation=='FINAL_BINDING_INPUT']
    assert {graph.entities[f.object].name for f in inputs}=={'args','kwargs'}


@pytest.mark.parametrize('body',['global saved\n saved=supplied','saved=supplied\n exec(code)','saved=supplied\n yield saved','saved=supplied\n del saved'])
def test_unsupported_dynamic_or_suspending_bindings(body):
    text='def retain(supplied):\n'+''.join(' '+line+'\n' for line in body.splitlines())
    graph=link_project([lower_source(text,'python','dynamic.py')]);assert not graph.diagnostics
    assert not any(f.relation=='FINAL_BINDING_INPUT' for f in graph.facts)
    assert any(f.relation=='BINDING_FLOW_STATUS' and f.object=='unsupported' for f in graph.facts)


@pytest.mark.parametrize('relation',['FINAL_BINDING_INPUT','BINDING_FLOW_STATUS'])
def test_registered_relations_on_a_graph_without_assignments(relation):
    graph=link_project([lower_source('pass','python','empty.py')])
    out=execute_rules(graph,[SavedRule('empty',f'query empty {{ require $a {relation} $b; emit $a,$b; }}')])
    assert out['complete'] and not out['matches']


@pytest.mark.parametrize('language',['javascript','typescript'])
@pytest.mark.parametrize('declaration',['let saved;','var saved;','let saved,other=0;','let saved /* no initializer */;'])
def test_declaration_without_value_is_not_an_unmodeled_assignment(language,declaration):
    text='function retain(supplied){'+declaration+'saved=supplied;}'
    graph=link_project([lower_source(text,language,'declaration')]);assert not graph.diagnostics
    native=[o for o in graph.operations if o.native_kind=='variable_declarator']
    assert native[0].kind=='DECLARATION'
    assert not any(f.subject==native[0].id and f.relation=='ASSIGNMENT_VALUE' for f in graph.facts)
    if len(native)>1:assert native[1].kind=='ASSIGN'
    assert any(f.relation=='FINAL_BINDING_INPUT' for f in graph.facts)


@pytest.mark.parametrize('language',['python','java','csharp','rust'])
@pytest.mark.parametrize('initialized',[False,True])
def test_bare_typed_declarations_and_explicit_initializers(language,initialized):
    initial='=supplied' if initialized else ''
    texts={
      'python':f'def retain(supplied):\n saved:int{initial}\n saved=supplied\n',
      'java':f'class C{{void retain(int supplied){{int saved{initial};saved=supplied;}}}}',
      'csharp':f'class C{{void retain(int supplied){{int saved{initial};saved=supplied;}}}}',
      'rust':f'fn retain(supplied:i32){{let mut saved:i32{initial};saved=supplied;}}',
    }
    graph=link_project([lower_source(texts[language],language,'typed')]);assert not graph.diagnostics
    retain=next(e.id for e in graph.entities.values() if e.name=='retain')
    declaration=next(o for o in graph.operations if o.owner==retain and o.native_kind=={'python':'assignment','java':'variable_declarator','csharp':'variable_declarator','rust':'let_declaration'}[language])
    assert declaration.kind==('ASSIGN' if initialized else 'DECLARATION')
    inputs=[f for f in graph.facts if f.relation=='FINAL_BINDING_INPUT']
    assert len(inputs)==1 and inputs[0].subject!=declaration.id
    assert any(f.relation=='BINDING_FLOW_STATUS' and f.object=='supported' for f in graph.facts)
