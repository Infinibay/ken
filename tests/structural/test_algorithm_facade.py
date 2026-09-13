"""Facade coordination: source-to-consumer flow versus broad field signatures."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


LANGUAGES = ['python', 'java', 'typescript']
FLOW_QUERY = '''query facade_flow {
 match "facade"(unit:$unit);
 require $unit HAS_METHOD $operation;
 require $unit HAS_FIELD $first;
 require $unit HAS_FIELD $second;
 require $first TYPE $first_type;
 require $second TYPE $second_type;
 different $first_type $second_type;
 require $operation HAS_CALL $producer;
 require $producer RECEIVER $first;
 require $producer RESULT $produced;
 require $operation HAS_CALL $consumer;
 require $consumer RECEIVER $second;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $produced VALUE_FLOW{0,3} $input as $flow;
 emit $unit,$operation,$producer,$consumer,$flow;
}'''


def source(language, mode='nested'):
    receiver = 'self' if language == 'python' else 'this'
    declaration = '' if language == 'python' else 'int ' if language == 'java' else 'let '
    producer = f'{receiver}.reader.read(key)'
    consumer = f'{receiver}.writer.write(value)'
    noise = ['metric=1+2', 'print(metric)'] if language == 'python' else [declaration+'metric=1+2', 'System.out.println(metric)' if language == 'java' else 'console.log(metric)']
    if mode in {'nested', 'nested-noise'}:
        statements = (noise if mode == 'nested-noise' else []) + [f'return {receiver}.writer.write({producer})']
    elif mode == 'linear':
        statements = [declaration+'value='+producer, *noise, 'return '+consumer]
    elif mode == 'overwritten':
        statements = [declaration+'value='+producer, *noise, 'value=0', 'return '+consumer]
    elif mode == 'reversed':
        statements = [declaration+'value=0', declaration+'result='+consumer, *noise, 'value='+producer, 'return result']
    else:
        statements = [producer, *noise, f'return {receiver}.writer.write(0)']
    if language == 'python':
        return '''class Reader:
 def read(self,key): return key
class Writer:
 def write(self,value): return value
class Surface:
 def __init__(self, reader:Reader, writer:Writer):
  self.reader=reader
  self.writer=writer
 def execute(self,key):
''' + ''.join('  '+s+'\n' for s in statements)
    if language == 'java':
        return '''class Reader {int read(int key){return key;}}
class Writer {int write(int value){return value;}}
class Surface {
 Reader reader; Writer writer;
 Surface(Reader reader,Writer writer){this.reader=reader;this.writer=writer;}
 int execute(int key){'''+';'.join(statements)+';} }'
    return '''class Reader {read(key:number):number{return key;}}
class Writer {write(value:number):number{return value;}}
class Surface {
 reader:Reader; writer:Writer;
 constructor(reader:Reader,writer:Writer){this.reader=reader;this.writer=writer;}
 execute(key:number):number {'''+';'.join(statements)+';} }'


def detect(language, mode, refined=True, evidence_mode='strict'):
    graph = link_project([lower_source(source(language, mode), language, 'facade.'+{'python':'py','java':'java','typescript':'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('facade-flow', FLOW_QUERY) if refined else named_rule('facade', registry)
    result = execute_rules(graph, [rule], registry=registry, evidence_mode=evidence_mode)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['nested','nested-noise'])
def test_strict_direct_value_handoff_survives_independent_work(language, mode):
    assert detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_two_delegations_do_not_prove_value_handoff(language):
    assert detect(language, 'discarded', refined=False)
    assert not detect(language, 'discarded')


@pytest.mark.parametrize('language', LANGUAGES)
def test_possible_mode_can_discover_handoff_through_local(language):
    assert detect(language, 'linear', evidence_mode='possible')


@pytest.mark.parametrize('language', LANGUAGES)
def test_strict_handoff_through_unchanged_local_with_intermediate_work(language):
    assert detect(language, 'linear')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['overwritten','reversed'])
def test_possible_flow_does_not_certify_assignment_stability_or_order(language, mode):
    # These are explicit limitations, not six correct algorithm detections.
    # Possible mode uses flow-insensitive assignment evidence in these cases.
    assert detect(language, mode, refined=False)
    assert detect(language, mode, evidence_mode='possible')
    assert not detect(language, mode, evidence_mode='strict')
