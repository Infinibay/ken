"""Implementation witnesses must retain the input they claim to use."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project

from .test_dispatch_table import SOURCES as DISPATCH
from .test_modern_patterns import SOURCES as INJECTION
from .test_queued_commands import LANGUAGES, source as queue_source
from .test_subclass_factories import source as subclass_source


@pytest.fixture(scope='module')
def registry():
    return query_registry(builtin_rules())


def matches(source, language, target, registry):
    if language == 'python':
        compile(source, '<modern-oracle>', 'exec')
    graph = link_project([lower_source(source, language, 'modern-oracle.' + language)])
    assert not graph.diagnostics
    out = Engine(query_graph(graph), registry).execute(registry[target])
    assert out['complete'], out
    return bool(out['matches'])


@pytest.mark.parametrize('language', list(INJECTION))
@pytest.mark.parametrize('change', ['positive', 'overwrite-field', 'overwrite-input'])
def test_object_injection_retains_its_witness(language, change, registry):
    source = INJECTION[language]
    prefix = 'self' if language == 'python' else 'this'
    null = 'None' if language == 'python' else 'null'
    assignment = f'{prefix}.dependency = incoming'
    if change == 'overwrite-field':
        source = source.replace(assignment, assignment + f'; {prefix}.dependency = {null}')
    if change == 'overwrite-input':
        source = source.replace(assignment, f'incoming = {null}; ' + assignment)
    assert matches(source, language, 'architecture.dependency-injection', registry) == (change == 'positive')


@pytest.mark.parametrize('language', list(DISPATCH))
@pytest.mark.parametrize('overwrite', [False, True])
def test_registration_does_not_keep_an_overwritten_handler(language, overwrite, registry):
    source = DISPATCH[language]
    receiver = 'self' if language == 'python' else 'r' if language == 'go' else 'this'
    null = 'None' if language == 'python' else 'nil' if language == 'go' else 'null'
    if overwrite:
        assignment = f'{receiver}.table[key] = handler'
        source = source.replace(assignment, assignment + f'; {receiver}.table[key] = {null}')
    assert matches(source, language, 'architecture.dispatch-table', registry) is not overwrite


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('clear_before', [False, True])
def test_batch_must_drain_entry_collection(language, clear_before, registry):
    source = queue_source(language)
    if clear_before:
        if language == 'python':
            source = source.replace('  for item in self.tasks:', '  self.tasks = []\n  for item in self.tasks:')
        elif language in {'javascript', 'typescript'}:
            source = source.replace('for (const item of this.tasks)', 'this.tasks = []; for (const item of this.tasks)')
        else:
            source = source.replace('for (Action item : this.tasks)', 'this.tasks.clear(); for (Action item : this.tasks)') if language == 'java' else source.replace('foreach (Action item in this.tasks)', 'this.tasks.Clear(); foreach (Action item in this.tasks)')
        assert source != queue_source(language), language
    assert matches(source, language, 'architecture.batch-work-queue', registry) is not clear_before


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
@pytest.mark.parametrize('overwrite', [False, True])
def test_base_alias_is_unique_and_ordered(language, overwrite, registry):
    source = subclass_source(language)
    if language == 'python':
        prefix = 'selected = base\n '
        if overwrite:
            prefix += 'selected = object\n '
        source = source.replace('class Derived(base)', prefix + 'class Derived(selected)')
    else:
        prefix = 'const selected = base;' if not overwrite else 'let selected = base; selected = Object;'
        source = source.replace('{return class', '{' + prefix + 'return class').replace('extends base', 'extends selected')
    assert matches(source, language, 'architecture.subclass-factory', registry) is not overwrite


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
@pytest.mark.parametrize('scalar', [False, True])
def test_resolved_adapter_cannot_return_a_scalar(language, scalar, registry):
    if language == 'python':
        source = 'def adapt(handler):\n return ' + ('42' if scalar else 'handler') + '\ndef wrap(next):\n def handler(x): return next(x)\n return adapt(handler)\n'
    else:
        source = 'function adapt(handler){return ' + ('42' if scalar else 'handler') + ';}function wrap(next){return adapt(x => next(x));}'
    assert matches(source, language, 'architecture.adapted-continuation-wrapper', registry) is not scalar


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
@pytest.mark.parametrize('finalizer', ['logging', 'break', 'return'])
def test_finalizer_cannot_cancel_explicit_retry(language, finalizer, registry):
    action = {'logging': 'audit()', 'break': 'break', 'return': 'return 0'}[finalizer]
    if language == 'python':
        source = 'def f():\n while True:\n  try:\n   return work()\n  except Exception:\n   continue\n  finally:\n   ' + action + '\n'
    else:
        source = 'function f(){for(;;){try{return work();}catch(e){continue;}finally{' + action + ';}}}'
    assert matches(source, language, 'resilience.exception-retry', registry) == (finalizer == 'logging')
