"""Observer algorithm contracts: interleaving, element identity and honest gaps.

These sources are parsed, never imported or executed. TypeScript shares the
ECMAScript family here; three parser languages do not mean three independent
runtime models.
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

from .test_collection_snapshots import LANGUAGES, source


def search(text, language):
    graph = link_project([lower_source(text, language, 'observer-algorithm')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('observer', registry)], registry=registry)
    assert result['complete']
    return {graph.entities[m['bindings']['$unit']].name for m in result['matches']}


def with_noise(text, language, location):
    """No shared objects are supplied to logging; arithmetic uses local literals."""
    if language == 'python':
        prefix = 'def trace(value): print(value)\n'
        if location == 'registration':
            text = text.replace('self.listeners.append(listener)',
                                'trace(1); self.listeners.append(listener); trace(2)')
        elif location == 'snapshot':
            text = text.replace('  xs=list(self.listeners)',
                                '  count=2+3\n  trace(count)\n  xs=list(self.listeners)\n  trace(4)')
        else:
            text = text.replace('   item.next(value)',
                                '   count=4+5\n   trace(count)\n   item.next(value)\n   trace(6)')
    else:
        prefix = ('function trace(value: number){console.log(value);}' if language == 'typescript'
                  else 'function trace(value){console.log(value);}')
        if location == 'registration':
            text = text.replace('this.listeners.push(listener);',
                                'trace(1);this.listeners.push(listener);trace(2);')
        elif location == 'snapshot':
            text = text.replace('let xs=Array.from(this.listeners);',
                                'const count=2+3;trace(count);let xs=Array.from(this.listeners);trace(4);')
        else:
            text = text.replace('item.next(value);',
                                'const count=4+5;trace(count);item.next(value);trace(6);')
    return prefix + text


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('location', ['registration', 'snapshot', 'delivery'])
@pytest.mark.parametrize('renamed', [False, True])
def test_independent_work_preserves_observer_algorithm(language, location, renamed):
    text = with_noise(source(language), language, location)
    expected = 'Subject'
    if renamed:
        for old, new in [('Subject', 'Channel'), ('listeners', 'receivers'),
                         ('subscribe', 'connect'), ('notify', 'broadcast'), ('item', 'receiver')]:
            text = text.replace(old, new)
        expected = 'Channel'
    assert search(text, language) == {expected}


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['different-registry', 'different-element', 'replace-snapshot', 'overwrite-element'])
def test_broken_provenance_is_rejected_with_logging_retained(language, mutation):
    text = with_noise(source(language), language, 'snapshot')
    py = language == 'python'
    if mutation == 'different-registry':
        text = text.replace('list(self.listeners)', 'list(self.others)') if py else text.replace('Array.from(this.listeners)', 'Array.from(this.others)')
    elif mutation == 'different-element':
        text = text.replace('item.next(value)', 'other.next(value)')
    elif mutation == 'replace-snapshot':
        text = text.replace('  for item', '  xs=[]\n  for item') if py else text.replace('for(const item', 'xs=[];for(const item')
    else:
        text = text.replace('   item.next(value)', '   item=other\n   item.next(value)') if py else text.replace('item.next(value)', 'item=other;item.next(value)')
    assert search(text, language) == set()


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Observer signature does not correlate the incoming event with callback arguments')
def test_event_delivery_contract_rejects_discarded_event(language):
    # This stricter named-event contract is not guaranteed by the current broad
    # Observer candidate rule; it must not be reported as supported coverage.
    text = source(language).replace('item.next(value)', 'item.next(0)')
    assert search(text, language) == set()


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Observer graph signature does not reject unreachable snapshot notification')
def test_unreachable_notification_is_not_an_observer_algorithm(language):
    text = source(language)
    text = text.replace('  for item', '  return\n  for item') if language == 'python' else text.replace('for(const item', 'return;for(const item')
    assert search(text, language) == set()
