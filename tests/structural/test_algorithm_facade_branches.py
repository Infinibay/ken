"""Facade flow distinguishes a call occurrence from its callee's identity.

Two mutually exclusive calls to the same reader remain may origins; neither
individual call result reaches the consumer on every path. A shared result
assigned in both arms is instead a must origin (argument occurrence matrix).
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
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


def source(language, mode):
    receiver = 'self' if language == 'python' else 'this'
    producer = f'{receiver}.reader.read(key)'
    consumer = f'{receiver}.writer.write(value)'
    if language == 'python':
        prefix = 'class Reader:\n def read(self,key): return key\nclass Writer:\n def write(self,value): return value\nclass Surface:\n def __init__(self, reader:Reader, writer:Writer):\n  self.reader=reader\n  self.writer=writer\n def execute(self, key, flag):\n'
        if mode == 'same-producer':
            body = (
                '  if flag:\n'
                f'   value = {producer}\n'
                '  else:\n'
                f'   value = {producer}\n'
                f'  return {consumer}\n'
            )
        elif mode == 'body-with-arm-overwrite':
            body = (
                f'  value = {producer}\n'
                '  if flag:\n'
                '   value = 0\n'
                f'  return {consumer}\n'
            )
        elif mode == 'single-arm-undefined':
            body = (
                '  if flag:\n'
                f'   value = {producer}\n'
                f'  return {consumer}\n'
            )
        else:
            raise ValueError(mode)
        return prefix + body
    if language == 'java':
        cls = 'class Reader{int read(int key){return key;}}class Writer{int write(int value){return value;}}class Surface{Reader reader;Writer writer;Surface(Reader reader,Writer writer){this.reader=reader;this.writer=writer;}int execute(int key,boolean flag){'
        if mode == 'same-producer':
            stmts = [f'if(flag){{value={producer};}}else{{value={producer};}}', f'return {consumer};']
        elif mode == 'body-with-arm-overwrite':
            stmts = [f'value={producer};', 'if(flag){value=0;}', f'return {consumer};']
        elif mode == 'single-arm-undefined':
            stmts = [f'if(flag){{value={producer};}}', f'return {consumer};']
        else:
            raise ValueError(mode)
        return cls + ';'.join(stmts) + ';}}'
    # typescript
    cls = 'class Reader{read(key:number):number{return key;}}class Writer{write(value:number):number{return value;}}class Surface{reader:Reader;writer:Writer;constructor(reader:Reader,writer:Writer){this.reader=reader;this.writer=writer;}execute(key:number,flag:boolean):number{'
    if mode == 'same-producer':
        stmts = [f'if(flag){{value={producer};}}else{{value={producer};}}', f'return {consumer};']
    elif mode == 'body-with-arm-overwrite':
        stmts = [f'value={producer};', 'if(flag){value=0;}', f'return {consumer};']
    elif mode == 'single-arm-undefined':
        stmts = [f'if(flag){{value={producer};}}', f'return {consumer};']
    else:
        raise ValueError(mode)
    return cls + ';'.join(stmts) + ';}}'


def detect(language, mode, evidence_mode='strict'):
    graph = link_project([lower_source(source(language, mode), language, 'facade.'+{'python':'py','java':'java','typescript':'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('facade-flow', FLOW_QUERY)
    result = execute_rules(graph, [rule], registry=registry, evidence_mode=evidence_mode)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_distinct_calls_to_same_producer_remain_may(language):
    assert not detect(language, 'same-producer', evidence_mode='strict')
    assert detect(language, 'same-producer', evidence_mode='possible')


@pytest.mark.parametrize('language', LANGUAGES)
def test_body_with_arm_overwrite_stays_may_in_strict(language):
    assert not detect(language, 'body-with-arm-overwrite', evidence_mode='strict')
    assert detect(language, 'body-with-arm-overwrite', evidence_mode='possible')


@pytest.mark.parametrize('language', LANGUAGES)
def test_single_arm_undefined_is_may_in_strict(language):
    assert not detect(language, 'single-arm-undefined', evidence_mode='strict')
    assert detect(language, 'single-arm-undefined', evidence_mode='possible')
