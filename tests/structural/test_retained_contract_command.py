"""Commands used through a retained nominal contract, with source-level contrasts."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule


LANGUAGES=['python','typescript','java','csharp','cpp']
CHANGES=['positive','renamed','no-retention','other-slot','overwritten-input','overwritten-slot',
         'receiver-overwritten','no-work','other-receiver','wrong-action','with-argument','no-contract']


def source(language,retention='setter',change='positive'):
    cpp=language=='cpp';python=language=='python';ts=language=='typescript'
    action='otherAction' if change=='wrong-action' else 'perform'
    argument='1' if change=='with-argument' else ''
    read='other' if change=='other-slot' else 'saved'
    work='other' if change=='other-receiver' else 'receiver'
    if python:
        setup='self.saved=input'
        if change=='no-retention':setup='pass'
        if change=='overwritten-input':setup='input=None;self.saved=input'
        if change=='overwritten-slot':setup+=';self.saved=None'
        ctor='self.receiver=receiver'+(';self.receiver=None' if change=='receiver-overwritten' else '')
        setter='__init__' if retention=='constructor' else 'store'
        body='pass' if change=='no-work' else f'self.{work}.work()'
        annotation='Foreign' if change=='no-contract' else 'Contract'
        text=f'''class Contract:
 def perform(self): pass
class Sink:
 def work(self): pass
class Job(Contract):
 receiver: Sink
 def __init__(self,receiver:Sink): {ctor}
 def {action}(self): {body}
class Invoker:
 saved: Contract
 other: Contract
 def {setter}(self,input:{annotation}): {setup}
 def flush(self): self.{read}.perform({argument})
'''
    else:
        null='nullptr' if cpp else 'null'
        contract='class Contract{public:virtual void perform()=0;};' if cpp else 'interface Contract{void perform();}' if not ts else 'interface Contract{perform():void;}'
        receiver_type='Sink*' if cpp else 'Sink'
        input_type='Foreign' if change=='no-contract' else 'Contract'
        if cpp:input_type+='*'
        store='saved=input;' if cpp else 'this.saved=input;'
        if change=='no-retention':store=''
        if change=='overwritten-input':store='input='+null+';'+store
        if change=='overwritten-slot':store+=('saved=' if cpp else 'this.saved=')+null+';'
        initialize='receiver=receiver;' if cpp else 'this.receiver=receiver;'
        receiver_extra=('this->receiver=' if cpp else 'this.receiver=')+null+';' if change=='receiver-overwritten' else ''
        work_call=f'{work}->work();' if cpp else f'this.{work}.work();'
        if change=='no-work':work_call=''
        dispatch=f'{read}->perform({argument});' if cpp else f'this.{read}.perform({argument});'
        if cpp:
            job_ctor=f'Job({receiver_type} receiver):receiver(receiver){{{receiver_extra}}}'
            if retention=='constructor':
                if change=='no-retention':setter=f'Invoker({input_type} input){{}}'
                else:
                    after=('input=nullptr;' if change=='overwritten-input' else '')+('saved=nullptr;' if change=='overwritten-slot' else '')
                    setter=f'Invoker({input_type} input):saved(input){{{after}}}'
            else:setter=f'void store({input_type} input){{{store}}}'
            text=contract+f'class Sink{{public:void work(){{}}}};class Job:public Contract{{Sink*receiver;Sink*other;public:{job_ctor}void {action}(){{{work_call}}}}};class Invoker{{Contract*saved;Contract*other;public:{setter}void flush(){{{dispatch}}}}};'
        elif ts:
            job_ctor=f'constructor(receiver:Sink){{{initialize}{receiver_extra}}}'
            setter=('constructor' if retention=='constructor' else 'store')+f'(input:{input_type}){{{store}}}'
            text=contract+f'class Sink{{work(){{}}}}class Job implements Contract{{receiver:Sink;other:Sink;{job_ctor}{action}(){{{work_call}}}}}class Invoker{{saved:Contract;other:Contract;{setter}flush(){{{dispatch}}}}}'
        else:
            inheritance='implements' if language=='java' else ':'
            job_ctor=f'public Job(Sink receiver){{{initialize}{receiver_extra}}}'
            setter=('public Invoker' if retention=='constructor' else 'public void store')+f'({input_type} input){{{store}}}'
            text=contract+f'class Sink{{public void work(){{}}}}class Job {inheritance} Contract{{Sink receiver;Sink other;{job_ctor}public void {action}(){{{work_call}}}}}class Invoker{{Contract saved;Contract other;{setter}public void flush(){{{dispatch}}}}}'
    if change=='renamed':
        for old,new in [('Contract','Protocol'),('Job','Envelope'),('Invoker','Dispatcher'),('perform','trigger'),('saved','pending'),('receiver','backend')]:
            text=re.sub(r'\b'+old+r'\b',new,text)
    return text


def detect(text,language):
    graph=link_project([lower_source(text,language,'command-example')]);assert not graph.diagnostics
    rules=builtin_rules()
    result=execute_rules(graph,[named_rule('command#retained-contract',rules)],registry=rules)
    assert result['complete']
    return graph,result


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('retention',['setter','constructor'])
@pytest.mark.parametrize('change',CHANGES)
def test_retained_contract_shape(language,retention,change):
    _,out=detect(source(language,retention,change),language)
    assert bool(out['matches'])==(change in {'positive','renamed'})


@pytest.mark.parametrize('language',LANGUAGES)
def test_public_operation_is_independent_of_command_action(language):
    text=source(language,change='no-work');graph,_=detect(text,language);rules=builtin_rules()
    result=execute_rules(graph,[SavedRule('usage','''query usage {
      match "command.retained_dispatch"(invoker:$invoker, storage:$field, dispatch:$call, contract:$contract);
      emit $invoker,$field,$call,$contract;
    }''')],registry=rules)
    assert result['complete'] and len(result['matches'])==1


@pytest.mark.parametrize('language',LANGUAGES)
def test_unrelated_retention_cannot_supply_another_invokers_dispatch(language):
    graph,_=detect(source(language,change='other-slot'),language);rules=builtin_rules()
    result=execute_rules(graph,[SavedRule('scoped_usage','''query scoped_usage {
      type_decl(name:"Invoker") as $invoker;
      match "command.retained_dispatch"(invoker:$invoker,storage:$field,dispatch:$call);
      emit $invoker,$field,$call;
    }''')],registry=rules)
    assert result['complete'] and not result['matches']
