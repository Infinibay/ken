"""Compose supplied-policy evidence with same-input/result consumption contracts."""
from __future__ import annotations

import pytest

from ken.structural.rules import SavedRule

from .test_strategy_binding_inputs import graph_and_result, source as policy_source

CASES = [('python', 'object'), ('java', 'object'), ('typescript', 'object'),
         ('python', 'callable'), ('typescript', 'callable')]

CONSUMED_POLICY = SavedRule('same_input_policy_result', '''query same_input_policy_result {
  match "strategy.supplied_policy"(unit:$unit, configure:$configure, policy:$policy);
  require $unit HAS_METHOD $algorithm;
  different $configure $algorithm;
  require $algorithm HAS_PARAMETER $input;
  parameter(receiver:false) as $input;
  require $algorithm HAS_CALL $invocation;
  any { require $invocation RECEIVER $policy; }
  or { require $invocation CALLEE_VALUE $policy; }
  call() as $invocation { has_argument(pos:0, kind:positional) as $argument; }
  require $argument VALUE $read;
  require $read LOADED_FROM $input;
  require $algorithm RETURNS_VALUE $result;
  require $invocation RESULT $result;
  emit $unit, $policy, $algorithm, $invocation, $input, $result;
}''')


def source(language: str, kind: str, mutation: str = '', noise: bool = True) -> str:
    text = policy_source(language, kind)
    receiver = 'self' if language == 'python' else 'this'
    call = receiver + '.policy' + ('.run' if kind == 'object' else '') + '(value)'
    invoked = call.replace('(value)', '(0)') if mutation == 'wrong-input' else call
    if language == 'python':
        audit = '\n  audit=17*3\n  print(audit)' if noise else ''
        overwrite = '\n  result=0' if mutation == 'overwrite-result' else ''
        if mutation == 'rebound-input':
            invoked = 'value=0\n  result=' + invoked
        else:
            invoked = 'result=' + invoked
        returned = 'value' if mutation == 'discard-result' else 'result'
        old = ' def apply(self,value): return ' + call
        new = ' def apply(self,value):\n  ' + invoked + audit + overwrite + '\n  return ' + returned
        assert old in text
        return text.replace(old, new)
    assignment = ('int result=' if language == 'java' else 'let result=') + invoked + ';'
    if mutation == 'rebound-input':
        assignment = 'value=0;' + assignment
    audit = ('int audit=17*3;System.out.println(audit);' if language == 'java' else
             'const audit=17*3;console.log(audit);') if noise else ''
    overwrite = 'result=0;' if mutation == 'overwrite-result' else ''
    returned = 'value' if mutation == 'discard-result' else 'result'
    old = 'return ' + call + (';' if language == 'java' else '')
    new = assignment + audit + overwrite + 'return ' + returned + ';'
    assert old in text
    return text.replace(old, new)


@pytest.mark.parametrize('language,kind', CASES)
@pytest.mark.parametrize('noise', [False, True])
def test_selected_policy_result_is_consumed_with_independent_work(language, kind, noise):
    text = source(language, kind, noise=noise)
    assert graph_and_result(text, language)[1]['matches']
    assert graph_and_result(text, language, CONSUMED_POLICY)[1]['matches']


@pytest.mark.parametrize('language,kind', CASES)
@pytest.mark.parametrize('mutation', ['wrong-input', 'discard-result', 'overwrite-result'])
def test_refined_usage_rejects_wrong_input_or_discarded_result(language, kind, mutation):
    text = source(language, kind, mutation)
    # Strategy can be void/effectful or accept transformed inputs. This rejection
    # belongs to the explicitly stronger identity-and-result contract only.
    assert graph_and_result(text, language)[1]['matches']
    assert not graph_and_result(text, language, CONSUMED_POLICY)[1]['matches']


@pytest.mark.parametrize('language,kind', CASES)
def test_entry_input_binding_is_not_reassigned_before_policy_invocation(language, kind):
    assert not graph_and_result(source(language, kind, 'rebound-input'), language, CONSUMED_POLICY)[1]['matches']
