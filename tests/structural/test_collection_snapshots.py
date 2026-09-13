"""Authored Observer reductions: copy identity, local aliases and callback setup."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript']


def source(language, mode='alias', callback=False):
    if language == 'python':
        subscribe = (' def subscribe(self):\n'
                     '  def register(listener): self.listeners.append(listener)\n'
                     '  setup(register)\n') if callback else (
                     ' def subscribe(self, listener): self.listeners.append(listener)\n')
        setup, iterable = '', 'list(self.listeners)'
        if mode != 'direct':
            setup, iterable = '  xs=list(self.listeners)\n', 'xs'
        if mode == 'chain':
            setup += '  ys=xs\n'
            iterable = 'ys'
        if mode == 'clear':
            setup += '  self.listeners.clear()\n'
        return ('class Subject:\n'
                ' def __init__(self): self.listeners=[]\n' + subscribe +
                ' def notify(self, value):\n' + setup +
                f'  for item in {iterable}:\n   item.next(value)\n')
    subscribe = ('constructor(){ setup(listener => {this.listeners.push(listener);}); }'
                 if callback else 'subscribe(listener){this.listeners.push(listener);}')
    setup, iterable = '', 'Array.from(this.listeners)'
    if mode != 'direct':
        setup, iterable = 'let xs=Array.from(this.listeners);', 'xs'
    if mode == 'chain':
        setup += 'const ys=xs;'
        iterable = 'ys'
    if mode == 'clear':
        setup += 'this.listeners.clear();'
    return ('class Subject { listeners=[]; ' + subscribe +
            'notify(value){' + setup + f'for(const item of {iterable}){{item.next(value);}}' + '}}')


def run(text, language):
    graph = link_project([lower_source(text, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('observer#snapshot-registry', registry)], registry=registry)
    assert result['complete']
    return graph, result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['direct', 'alias', 'chain', 'clear'])
@pytest.mark.parametrize('callback', [False, True])
def test_snapshot_registration_and_notification(language, mode, callback):
    graph, matches = run(source(language, mode, callback), language)
    assert len(matches) == 1
    assert graph.entities[matches[0]['bindings']['$unit']].name == 'Subject'


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-copy', 'other-register', 'overwrite', 'rebind-item',
                                    'other-call', 'no-invocation', 'late-assignment', 'conditional-alias'])
def test_near_misses_do_not_connect_unrelated_elements(language, mutation):
    text = source(language)
    py = language == 'python'
    if mutation == 'other-copy':
        text = text.replace('list(self.listeners)', 'list(self.others)') if py else text.replace('Array.from(this.listeners)', 'Array.from(this.others)')
    elif mutation == 'other-register':
        text = text.replace('listeners.append', 'others.append').replace('listeners.push', 'others.push')
    elif mutation == 'overwrite':
        text = text.replace('  for item', '  xs=[]\n  for item') if py else text.replace('for(const', 'xs=[];for(const')
    elif mutation == 'rebind-item':
        text = text.replace('   item.next', '   item=other\n   item.next') if py else text.replace('item.next', 'item=other;item.next')
    elif mutation == 'other-call':
        text = text.replace('item.next', 'other.next')
    elif mutation == 'no-invocation':
        text = text.replace('item.next(value)', 'pass' if py else 'item')
    elif mutation == 'late-assignment':
        assignment = '  xs=list(self.listeners)\n' if py else 'let xs=Array.from(this.listeners);'
        text = text.replace(assignment, '')
        text = text + assignment if py else text[:-2] + assignment + '}}'
    else:
        text = text.replace('  xs=list(self.listeners)', '  if value:\n   xs=list(self.listeners)') if py else text.replace('let xs=Array.from(this.listeners);', 'if(value){var xs=Array.from(this.listeners);}')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_unconsumed_registration_callback_is_not_a_subscription(language):
    text = source(language, callback=True)
    text = text.replace('  setup(register)\n', '') if language == 'python' else text.replace('setup(listener => {this.listeners.push(listener);});', 'const unused=listener => {this.listeners.push(listener);};')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_direct_callable_elements(language):
    assert run(source(language).replace('item.next(value)', 'item(value)'), language)[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_application_symbols_does_not_change_matches(language):
    text = source(language, callback=True)
    for before, after in [('Subject', 'Hub'), ('listeners', 'receivers'), ('listener', 'receiver'), ('notify', 'broadcast'), ('item', 'entry')]:
        text = text.replace(before, after)
    assert run(text, language)[1]


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
@pytest.mark.parametrize('prefix', ['const Array=fake;', 'import {Array} from "custom";', 'Array.from=fake;'])
def test_replaced_array_model_is_rejected(language, prefix):
    assert run(prefix + source(language), language)[1] == []


@pytest.mark.parametrize('prefix', ['list = custom\n', 'from custom import list\n', 'def list(xs): return []\n'])
def test_replaced_python_builtin_is_rejected(prefix):
    assert run(prefix + source('python'), 'python')[1] == []


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_array_from_mapper_does_not_preserve_listener_identity(language):
    text = source(language).replace('Array.from(this.listeners)', 'Array.from(this.listeners, x => other)')
    assert run(text, language)[1] == []


def test_tuple_snapshot_keeps_python_callback_elements():
    assert run(source('python').replace('list(self.listeners)', 'tuple(self.listeners)'), 'python')[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_snapshot_alias_from_containing_block_can_feed_conditional_loop(language):
    text = source(language)
    if language == 'python':
        text = text.replace('  for item', '  if value:\n   for item').replace('   item.next', '    item.next')
    else:
        text = text.replace('for(const', 'if(value){for(const') + '}'
    assert run(text, language)[1]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['mutator', 'escape', 'index-write', 'other-alias-mutator', 'dynamic'])
def test_mutated_or_escaped_snapshots_have_no_iteration_provenance(language, mutation):
    text = source(language)
    py = language == 'python'
    statements = {
        'mutator': 'xs.append(other)' if py else 'xs.push(other);',
        'escape': 'change(xs)' if py else 'change(xs);',
        'index-write': 'xs[0]=other' if py else 'xs[0]=other;',
        'other-alias-mutator': 'ys=xs\n  ys.append(other)' if py else 'const ys=xs;ys.push(other);',
        'dynamic': 'exec(code)' if py else 'eval(code);',
    }
    text = text.replace('  for item', '  ' + statements[mutation] + '\n  for item') if py else text.replace('for(const', statements[mutation] + 'for(const')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_block_shadowing_the_iteration_element_is_not_notification(language):
    text = source(language).replace('item.next(value);', '{const item=other;item.next(value);}')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_nested_callback_does_not_imply_element_invocation(language):
    text = source(language)
    text = text.replace('   item.next(value)', '   def unused(): item.next(value)') if language == 'python' else text.replace('item.next(value);', 'const unused=()=>item.next(value);')
    assert run(text, language)[1] == []


@pytest.mark.parametrize('language', LANGUAGES)
def test_loop_binding_cannot_overwrite_the_snapshot_alias(language):
    text = source(language)
    if language == 'python':
        text = text.replace('  for item', '  for xs in others:\n   pass\n  for item')
    else:
        text = text.replace('for(const item', 'for(xs of others){} for(const item')
    assert run(text, language)[1] == []
