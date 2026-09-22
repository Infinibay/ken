"""Condition snapshots inside loops never borrow a previous iteration's value."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


LANGUAGES = ['python', 'go', 'javascript', 'typescript']


def source(language, mode):
    bodies = {
        'plain': ['accepted = callback(item)'],
        'noise': ['accepted = callback(item)', 'log(item)'],
        'alias': ['saved = callback(item)', 'accepted = saved', 'saved = True'],
        'overwrite': ['accepted = callback(item)', 'accepted = True'],
        'conditional': ['if flag:', ' accepted = callback(item)'],
        'join': ['accepted = callback(item)', 'if flag:', ' accepted = True'],
        'continue': ['accepted = callback(item)', 'if flag:', ' accepted = True', ' continue'],
        'break': ['accepted = callback(item)', 'if flag:', ' accepted = True', ' break'],
        'prior': [],
        'unreachable': ['break', 'accepted = callback(item)'],
    }
    lines = bodies[mode] + ['if accepted == False:', ' break']
    if language == 'python':
        prefix = ' accepted = callback(0)\n' if mode == 'prior' else ''
        return 'def Each(items, callback, flag):\n' + prefix + ' for item in items:\n' + '\n'.join('  ' + line for line in lines) + '\n'
    body = ''
    block = False
    declared = set()
    for line in lines:
        if block and not line.startswith(' '):
            body += '};'
            block = False
        statement = line.strip().replace('True', 'true').replace('False', 'false')
        if statement.startswith('if '):
            condition = statement[3:-1]
            body += ('if ' + condition if language == 'go' else 'if (' + condition + ')') + '{'
            block = True
        else:
            if ' = ' in statement:
                name = statement.split(' = ')[0]
                if name not in declared:
                    declared.add(name)
                    statement = statement.replace(' = ', ' := ', 1) if language == 'go' else 'let ' + statement
            body += statement + ';'
    if block:
        body += '}'
    prefix = ('accepted := callback(0);' if language == 'go' else 'let accepted = callback(0);') if mode == 'prior' else ''
    if language == 'go':
        return 'package p\nfunc Each(items []int, callback func(int) bool, flag bool){' + prefix + 'for _,item:=range items{' + body + '}}'
    params = 'items, callback, flag' if language == 'javascript' else 'items:number[], callback:(item:number)=>boolean, flag:boolean'
    return 'function Each(' + params + '){' + prefix + 'for(const item of items){' + body + '}}'


def callback_origins(graph):
    callbacks = {fact.subject for fact in graph.facts if fact.relation == 'CALLEE_NAME' and fact.object == 'callback'}
    bindings = {eid for eid, entity in graph.entities.items() if entity.name == 'accepted'}
    reads = {fact.subject for fact in graph.facts if fact.relation == 'BINDING_REFERENCE' and fact.object in bindings}
    return [fact for fact in graph.facts if fact.relation == 'READ_ORIGIN'
            and fact.subject in reads and fact.object in callbacks]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['plain', 'noise', 'alias', 'continue', 'break'])
def test_same_iteration_origins_survive_independent_work_and_terminated_paths(language, mode):
    graph = link_project([lower_source(source(language, mode), language, 'sample')])
    assert not graph.diagnostics
    facts = callback_origins(graph)
    assert facts and all(fact.attrs['modality'] == 'must' for fact in facts)
    assert not any(fact.relation == 'RETURN_FLOW_STATUS' and fact.object == 'supported' for fact in graph.facts)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['overwrite', 'prior', 'unreachable', 'conditional', 'join'])
def test_missing_or_replaced_origin_never_becomes_must(language, mode):
    graph = link_project([lower_source(source(language, mode), language, 'sample')])
    assert not graph.diagnostics
    facts = callback_origins(graph)
    assert not any(fact.attrs['modality'] == 'must' for fact in facts)
    if mode in {'overwrite', 'prior', 'unreachable'}:
        assert not facts


def test_previous_iteration_assignment_does_not_feed_next_iteration_condition():
    source = 'def Each(items, callback):\n for item in items:\n  if accepted == False:\n   break\n  accepted = callback(item)\n'
    graph = link_project([lower_source(source, 'python', 'sample')])
    assert not callback_origins(graph)


def test_nested_loop_does_not_preserve_outer_snapshot():
    source = 'def Each(items, callback):\n for item in items:\n  accepted = callback(item)\n  for other in items:\n   accepted = True\n  if accepted == False:\n   break\n'
    graph = link_project([lower_source(source, 'python', 'sample')])
    assert not callback_origins(graph)


@pytest.mark.parametrize('language,source', [
    ('go', 'package p\nfunc Each(items []int, callback func(int) bool){accepted := true; pointer := &accepted; for _,item:=range items{accepted = callback(item); mutate(pointer); if accepted==false{break}}}'),
    ('javascript', 'function Each(items,callback){for(const item of items){let accepted=callback(item); if((accepted=true)){log(item);} if(accepted==false){break;}}}'),
    ('javascript', 'function Each(items,callback){let accepted=true; for(const item of items){let accepted=callback(item);} if(accepted==false){log(items);}}'),
])
def test_indirect_or_embedded_writes_and_shadowing_publish_no_stale_origin(language, source):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    assert not callback_origins(graph)


def test_unknown_alternative_retains_may_instead_of_becoming_must():
    graph = link_project([lower_source(source('python', 'conditional'), 'python', 'sample')])
    facts = callback_origins(graph)
    assert facts and all(fact.attrs['modality'] == 'may' for fact in facts)
