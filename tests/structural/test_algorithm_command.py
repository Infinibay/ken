"""Command algorithm interleaving atop retained-contract source fixtures."""
import pytest

from .test_gof_executable import evaluate
from .test_retained_contract_command import LANGUAGES, source


def instrument(text, language, location):
    if language == 'python':
        operation = 'self.receiver.work()' if location == 'action' else 'self.saved.perform()'
        replacement = 'metric=2+3;print(metric);' + operation + ';print(4)'
    else:
        operation = ('receiver->work();' if language == 'cpp' else 'this.receiver.work();') if location == 'action' else ('saved->perform();' if language == 'cpp' else 'this.saved.perform();')
        if language == 'java':
            noise = 'int metric=2+3;System.out.println(metric);'
        elif language == 'typescript':
            noise = 'const metric=2+3;console.log(metric);'
        elif language == 'csharp':
            noise = 'int metric=2+3;System.Console.WriteLine(metric);'
        else:
            noise = 'int metric=2+3;(void)metric;'
        replacement = noise + operation
    # Some negatives intentionally remove the operation being instrumented.
    return text.replace(operation, replacement)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('retention', ['setter', 'constructor'])
@pytest.mark.parametrize('location', ['action', 'invoker', 'both'])
def test_retained_command_tolerates_work_around_activation(language, retention, location):
    text = source(language, retention)
    for stage in (['action', 'invoker'] if location == 'both' else [location]):
        text = instrument(text, language, stage)
    assert evaluate(text, language, 'command')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('change', ['other-slot', 'overwritten-input', 'receiver-overwritten', 'no-work'])
def test_retention_and_action_identity_survive_negative_contrasts(language, change):
    # Keep independent work in the invoker while breaking one required relation.
    text = instrument(source(language, change=change), language, 'invoker')
    assert not evaluate(text, language, 'command')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Retained-contract signature does not prove field identity at runtime dispatch')
def test_received_command_identity_contract_rejects_dispatch_after_clear(language):
    text = source(language)
    if language == 'python':
        text = text.replace('self.saved.perform()', 'self.saved=None;self.saved.perform()')
    elif language == 'cpp':
        text = text.replace('saved->perform();', 'saved=nullptr;saved->perform();')
    else:
        text = text.replace('this.saved.perform();', 'this.saved=null;this.saved.perform();')
    assert not evaluate(text, language, 'command')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Command actions with explicit execution context are excluded by zero-arity variants')
def test_execution_context_is_a_valid_command_parameter(language):
    text = source(language)
    if language == 'python':
        text = text.replace('perform(self)', 'perform(self, context)').replace('self.saved.perform()', 'self.saved.perform(1)')
    elif language == 'typescript':
        text = text.replace('perform()', 'perform(context:number)').replace('this.saved.perform(context:number)', 'this.saved.perform(1)')
    else:
        text = text.replace('perform()', 'perform(int context)')
        text = text.replace('saved->perform(int context)', 'saved->perform(1)').replace('this.saved.perform(int context)', 'this.saved.perform(1)')
    assert evaluate(text, language, 'command')


def with_payload(language, discard=False):
    text = source(language)
    if language == 'python':
        text = text.replace('work(self)', 'work(self, data)')
        text = text.replace('receiver:Sink): self.receiver=receiver', 'receiver:Sink, data:int): self.receiver=receiver;self.payload=data')
        text = text.replace('self.receiver.work()', 'self.receiver.work(0)' if discard else 'self.receiver.work(self.payload)')
    elif language == 'typescript':
        text = text.replace('work(){}', 'work(data:number){}').replace('receiver:Sink;other:Sink;', 'receiver:Sink;other:Sink;payload:number;')
        text = text.replace('constructor(receiver:Sink){this.receiver=receiver;}', 'constructor(receiver:Sink,data:number){this.receiver=receiver;this.payload=data;}')
        text = text.replace('this.receiver.work()', 'this.receiver.work(0)' if discard else 'this.receiver.work(this.payload)')
    else:
        text = text.replace('void work(){}', 'void work(int data){}').replace('Sink receiver;Sink other;', 'Sink receiver;Sink other;int payload;')
        text = text.replace('Job(Sink receiver){this.receiver=receiver;}', 'Job(Sink receiver,int data){this.receiver=receiver;this.payload=data;}')
        text = text.replace('this.receiver.work()', 'this.receiver.work(0)' if discard else 'this.receiver.work(this.payload)')
    assert 'payload' in text
    return text


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
def test_command_can_retain_receiver_and_payload(language):
    assert evaluate(with_payload(language), language, 'command')


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.xfail(strict=True, reason='Command signature does not correlate constructor-captured payload with work arguments')
def test_captured_payload_contract_rejects_discarded_data(language):
    assert not evaluate(with_payload(language, discard=True), language, 'command')
