"""Configuration is the final direct write, not a historical parameter assignment."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,execute_rules,named_rule
from .test_builder_configuration import SOURCES

EXTRA={
 'cpp':'class Product {public: Product(int v){}}; class Assembly {int state; public: void configure(int value){this->state=value;} Product *finish(){return new Product(this->state);}};',
 'rust':'struct Product{value:i32} struct Assembly{state:i32} impl Assembly{fn configure(&mut self,mut value:i32){self.state=value;} fn finish(&self)->Product{Product{value:self.state}}}',
 'go':'package p\ntype Product struct{Value int}\ntype Assembly struct{state int}\nfunc(a *Assembly) configure(value int){a.state=value}\nfunc(a *Assembly) finish()*Product{return &Product{Value:a.state}}',
}
LANGUAGES=[*SOURCES,*EXTRA]
CASES=['positive','renamed','overwrite','rebind-before','rebind-after','constant','compound','branch','return-before','dead-overwrite','final-input','fluent']


def example(language,case):
    source={**SOURCES,**EXTRA}[language]
    prefix='self.' if language in {'python','rust'} else 'a.' if language=='go' else 'this->' if language=='cpp' else 'this.'
    target=prefix+'state'
    assignment=target+'=value'
    sep='\n  ' if language=='python' else ';'
    ret='return'
    changes={
     'overwrite':assignment+sep+target+'=0',
     'rebind-before':'value=0'+sep+assignment,
     'rebind-after':assignment+sep+'value=0',
     'constant':target+'=0',
     'compound':target+'+=value',
     'return-before':ret+sep+assignment,
     'dead-overwrite':assignment+sep+ret+sep+target+'=0',
     'final-input':target+'=0'+sep+assignment,
    }
    if case=='branch':
        changes[case]=('if value>0:\n   '+assignment if language=='python' else
                       ('if value>0 {'+assignment+';}' if language in {'rust','go'} else 'if(value>0){'+assignment+';}'))
    if case=='fluent':
        receiver='self' if language in {'python','rust'} else 'a' if language=='go' else 'this'
        changes[case]=assignment+sep+'return '+receiver+(';' if language!='python' else '')
        if language in {'java','csharp','cpp'}:source=source.replace('void configure','Assembly'+(' *' if language=='cpp' else ' ')+'configure')
        if language=='rust':source=source.replace('mut value:i32){','mut value:i32)->&mut Self{')
        if language=='go':source=source.replace('configure(value int){','configure(value int)*Assembly{')
    if case in changes:
        if language=='python':
            source=source.replace('def configure(self, value): '+assignment,'def configure(self, value):\n  '+changes[case])
        else:source=source.replace(assignment,changes[case])
    if case=='renamed':
        source=source.replace('Assembly','Assembler').replace('Product','Result').replace('configure','apply').replace('state','pending')
    return source.replace(';;',';')


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_final_direct_instance_field_input(language,case):
    graph=link_project([lower_source(example(language,case),language,'builder-source')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    owner=next(e.id for e in graph.entities.values() if e.kind=='CALLABLE' and e.name in {'configure','apply'})
    operations={o.id for o in graph.operations if o.owner==owner}
    actual=[f for f in graph.facts if f.relation=='FINAL_MEMBER_INPUT' and f.subject in operations]
    expected=case in {'positive','renamed','dead-overwrite','final-input','fluent'}
    assert bool(actual)==expected,(language,case,actual)
    states=[f for f in graph.facts if f.relation=='MEMBER_FLOW_STATUS' and f.subject==owner]
    if not (language=='rust' and case=='compound'):
        assert states
    if actual:
        assert len(actual)==1
        assert graph.entities[actual[0].object].kind=='PARAMETER'
        assert actual[0].attrs['basis']=='linear-syntax'
    # Construction argument form is independently supported in these six languages.
    if language not in {'rust','go'}:
        rules=builtin_rules();result=execute_rules(graph,[named_rule('builder#mutable-product',rules)],registry=rules)
        assert result['complete'] and bool(result['matches'])==expected,result


@pytest.mark.parametrize('language',['java','csharp','cpp'])
def test_implicit_receiver_field_assignment(language):
    text=example(language,'positive').replace('this->','').replace('this.','')
    graph=link_project([lower_source(text,language,'implicit')]);assert not graph.diagnostics
    rule=named_rule('builder#mutable-product',builtin_rules())
    out=execute_rules(graph,[rule],registry=builtin_rules())
    assert out['complete'] and len(out['matches'])==1,out


@pytest.mark.parametrize('assignment',[
 'value,other=0,0', 'a.state,value=value,0', 'value,a.state=0,value', 'a.state,other=value,0',
])
@pytest.mark.parametrize('before',[False,True])
def test_go_parallel_assignment_is_not_a_precise_scalar_write(assignment,before):
    scalar='a.state=value'
    body=assignment+';'+scalar if before else scalar+';'+assignment
    graph=link_project([lower_source('package p\ntype A struct{state int}\nfunc(a *A) f(value int,other int){'+body+'}','go','parallel')])
    assert not graph.diagnostics
    assert not [f for f in graph.facts if f.relation=='FINAL_MEMBER_INPUT']
    states=[f for f in graph.facts if f.relation=='MEMBER_FLOW_STATUS']
    assert len(states)==1 and states[0].object=='unsupported'
    assert states[0].attrs['reason']=='unmodeled-write'
