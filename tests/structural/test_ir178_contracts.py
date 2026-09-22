"""Read-site evidence, expression identity and optional algorithm contracts."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from .contract_support import contract_matches
from .test_algorithm_adapter import source as adapter
from .test_algorithm_visitor import source as visitor
from .test_algorithm_interpreter import source as interpreter

LANGUAGES = ('python', 'java', 'typescript')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['baseline', 'alias', 'overwrite', 'after-use', 'nested', 'constant-first'])
def test_conversion_snapshots_are_taken_at_evaluation(language, mutation):
    text = adapter(language)
    if mutation == 'alias':
        text = text.replace('converted=value*2', 'converted=value*2').replace('perform(converted)', 'perform(converted)')
        # Save the computation, then overwrite its operand. The computed value
        # still came from the old input, although the input binding changed.
        text = text.replace('result=self', 'value=0\n  result=self') if language == 'python' else text.replace('int result=', 'value=0;int result=').replace('let result=', 'value=0;let result=')
    elif mutation == 'overwrite':
        text = text.replace('result=self', 'converted=0\n  result=self') if language == 'python' else text.replace('int result=', 'converted=0;int result=').replace('let result=', 'converted=0;let result=')
        text = text.replace('const converted', 'let converted')
    elif mutation == 'after-use':
        text = text.replace('return result+1', 'converted=0\n  return result+1') if language == 'python' else text.replace('return result+1', 'converted=0;return result+1')
        text = text.replace('const converted', 'let converted')
    elif mutation == 'nested':
        text = text.replace('value*2', '(value*2)+3')
    elif mutation == 'constant-first':
        text = text.replace('value*2', '2*value')
    assert bool(contract_matches(text, language, 'adapter.input_conversion')) == (mutation != 'overwrite')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('after', [False, True])
def test_receiver_write_after_dispatch_does_not_revoke_the_call(language, after):
    statement = 'visitor=Visitor()' if language == 'python' else 'visitor=new Visitor();'
    text = visitor(language, **{('after' if after else 'before'): statement})
    assert bool(contract_matches(text, language, 'visitor.result_forwarding')) == after


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', ['none', 'before', 'between', 'both'])
def test_binary_contract_accepts_different_grammars_and_noise(language, noise):
    assert contract_matches(interpreter(language, 'wrong-combine', noise), language, 'interpreter.binary_result')


@pytest.mark.parametrize('language', LANGUAGES)
def test_value_nodes_with_same_start_have_distinct_identity(language):
    text = adapter(language, returned='1+(result*2)')
    graph = IR.from_dict(link_project([lower_source(text, language, 'overlap.'+language)]).to_dict())
    assert not graph.diagnostics
    assert not any(f.subject == f.object for f in graph.facts if f.relation == 'EXPRESSION_OPERAND')
    assert contract_matches(text, language, 'adapter.output_conversion')


@pytest.mark.parametrize('kind', ['classmethod', 'staticmethod'])
@pytest.mark.parametrize('mutation', ['positive', 'decorated', 'instance', 'other-owner', 'field-shadow'])
def test_python_class_descriptor_resolution_is_bounded(kind, mutation):
    parameter = 'cls, value' if kind == 'classmethod' else 'value'
    text = f'class Provider:\n @{kind}\n def get({parameter}): return value\n'
    text += 'def use(): return Provider.get(1)\n'
    if mutation == 'decorated':
        text = text.replace(f' @{kind}', f' @wrapper\n @{kind}')
    elif mutation == 'instance':
        text = text.replace(f' @{kind}\n', '').replace(f'get({parameter})', 'get(self, value)')
    elif mutation == 'other-owner':
        text = text.replace('Provider.get', 'Missing.get')
    elif mutation == 'field-shadow':
        text = text.replace('def use()', ' get = other\ndef use()')
    graph = link_project([lower_source(text, 'python', 'descriptor.py')])
    assert not graph.diagnostics
    matches = [f for f in graph.facts if f.relation == 'TARGET' and f.attrs.get('basis') == 'direct-class-static']
    assert bool(matches) == (mutation == 'positive')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['', 'discard-left', 'discard-both', 'overwrite-result', 'wrong-combine'])
def test_context_free_grammar_consumes_both_child_results(language, mutation):
    text = interpreter(language, mutation)
    if language == 'python':
        text = text.replace('evaluate(self, context)', 'evaluate(self)').replace('evaluate(context)', 'evaluate()')
    elif language == 'java':
        text = text.replace('evaluate(int context)', 'evaluate()').replace('evaluate(context)', 'evaluate()')
    else:
        text = text.replace('evaluate(context: number)', 'evaluate()').replace('evaluate(context)', 'evaluate()')
    assert bool(contract_matches(text, language, 'interpreter#context-free-binary')) == (mutation in {'', 'wrong-combine'})


@pytest.mark.parametrize('language', ['java', 'csharp'])
@pytest.mark.parametrize('alternative', ['zero', 'same-arity', 'optional', 'variadic'])
def test_constructor_arity_only_disambiguates_fixed_signatures(language, alternative):
    other = {'zero': 'public Item(){}', 'same-arity': 'public Item(string text){}',
             'optional': 'public Item(int x,int y=0){}',
             'variadic': 'public Item(params int[] values){}'}[alternative]
    if language == 'java':
        if alternative == 'optional':
            other = 'public Item(int... values){}'  # Java has no optional parameters.
        other = other.replace('string', 'String').replace('params int[]', 'int...')
    text = 'class Item {int value;public Item(int value){this.value=value;}' + other + '}'
    text += 'class Client {void run(){new Item(1);}}'
    graph = link_project([lower_source(text, language, 'overloads.'+language)])
    assert not graph.diagnostics
    targets = [f for f in graph.facts if f.relation == 'CONSTRUCTOR_TARGET']
    assert bool(targets) == (alternative == 'zero')
    if targets:
        assert targets[0].attrs['basis'] == 'unique-fixed-arity'


@pytest.mark.parametrize('mutation', ['positive', 'ignored-input', 'overwritten-field', 'published-self', 'only-delegation'])
def test_java_prototype_with_delegating_overloaded_constructor(mutation):
    assignment = 'this.value=value;'
    if mutation == 'ignored-input':
        assignment = 'this.value=0;'
    elif mutation == 'overwritten-field':
        assignment += 'this.value=0;'
    elif mutation == 'published-self':
        assignment += 'publish(this);'
    elif mutation == 'only-delegation':
        assignment = ''
    text = '''class Item {
      int value;
      Item(){System.out.println("creating");}
      Item(int value){this();''' + assignment + '''}
      Item duplicate(){return new Item(this.value);}
    }'''
    assert bool(contract_matches(text, 'java', 'prototype#explicit-copy')) == (mutation == 'positive')
