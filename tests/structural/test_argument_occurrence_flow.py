"""Read-site provenance must distinguish values from calls to the same function."""
import json

import pytest

from ken.structural import evaluate_query, link_project, lower_source
from ken.structural.kenql import query_graph
from ken.structural.model import IR

LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']
QUERY = '''query handoff {
 call(name: make) as $producer;
 require $producer RESULT $value;
 call(name: take) as $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $value VALUE_FLOW{1,1} $input as $flow;
 emit $producer, $consumer;
}'''


def source(language, mode):
    decl = '' if language == 'python' else 'let ' if language in {'javascript', 'typescript'} else 'int '
    statements = {
        'linear': [decl+'x=make(1)', 'take(x)', 'return 0'],
        'overwrite': [decl+'x=make(1)', 'x=make(2)', 'return take(x)'],
        'future': [decl+'x=0', 'take(x)', 'x=make(1)', 'return 0'],
        'alias': [decl+'x=make(1)', decl+'saved=x', 'x=make(2)', 'return take(saved)'],
        'nested': [decl+'x=make(1)', 'return outer(take(x))'],
        'rhs': [decl+'x=make(1)', 'x=take(x)', 'return x'],
        'void': [decl+'x=make(1)', 'take(x)'],
        'unreachable': [decl+'x=make(1)', 'return 0', 'take(x)'],
    }
    if mode in {'distinct-branches', 'shared-branches', 'overwritten-branch'}:
        if mode == 'distinct-branches':
            initial = decl+'x=0'
            left, right = 'x=make(1)', 'x=make(2)'
        elif mode == 'shared-branches':
            initial = decl+'saved=make(1)\n'+decl+'x=0'
            left = right = 'x=saved'
        else:
            initial = decl+'x=make(1)'
            left, right = 'x=0', 'x=x'
        if language == 'python':
            statements[mode] = [initial, f'if flag:\n {left}\nelse:\n {right}', 'return take(x)']
        else:
            statements[mode] = [initial.replace('\n', ';'), f'if(flag){{{left};}}else{{{right};}}', 'return take(x)']
    if language == 'python':
        return ('def make(n): return n\ndef take(n): return n\ndef outer(n): return n\n'
                'def run(flag):\n' + '\n'.join(' '+line for s in statements[mode] for line in s.splitlines())+'\n')
    body = ';'.join(statements[mode])+';'
    if language in {'javascript', 'typescript'}:
        return ('function make(n){return n;}function take(n){return n;}function outer(n){return n;}'
                'function run(flag){'+body+'}')
    boolean = 'boolean' if language == 'java' else 'bool'
    returns = 'void' if mode == 'void' else 'int'
    return ('class Sample {int make(int n){return n;}int take(int n){return n;}int outer(int n){return n;}'
            f'{returns} run({boolean} flag){{'+body+'}}')


def graph_for(language, mode, path='sample'):
    graph = link_project([lower_source(source(language, mode), language, path)])
    assert not graph.diagnostics, graph.diagnostics
    return graph


def producers_at_take(graph):
    view = query_graph(graph).ir
    calls = sorted((e for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'make'),
                   key=lambda e: e.attrs['start_byte'])
    take = next(e.id for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'take')
    argument = next(f.object for f in view.facts if f.relation == 'ARGUMENT' and f.subject == take)
    value = next(f.object for f in view.facts if f.relation == 'VALUE' and f.subject == argument)
    certain = {f.subject for f in view.facts if f.relation == 'VALUE_FLOW' and f.object == value
               and f.attrs.get('modality') == 'must'}
    return {i for i, call in enumerate(calls) if call.id+'/result' in certain}


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode,expected', [
    ('linear', {0}), ('overwrite', {1}), ('future', set()), ('alias', {0}),
    ('nested', {0}), ('rhs', {0}), ('void', {0}), ('unreachable', set()),
    ('distinct-branches', set()), ('shared-branches', {0}), ('overwritten-branch', set()),
])
def test_argument_has_exact_live_call_origin(language, mode, expected):
    graph = graph_for(language, mode)
    assert producers_at_take(graph) == expected
    result = evaluate_query(graph, QUERY)
    assert result['complete']
    assert len(result['matches']) == len(expected)


@pytest.mark.parametrize('language', LANGUAGES)
def test_call_mapping_includes_owner_and_file(language):
    # Identical offsets in two files must not map both call operations to file A.
    units = [lower_source(source(language, 'overwrite'), language, path) for path in ['a', 'b']]
    graph = link_project(units)
    call_paths = {graph.entities[f.subject].path for f in graph.facts if f.relation == 'ARGUMENT_ORIGIN'}
    assert call_paths == {'a', 'b'}
    for fact in graph.facts:
        if fact.relation == 'ARGUMENT_ORIGIN':
            assert all(graph.entities[value].path == graph.entities[fact.subject].path
                       for value in fact.attrs['origins'])


def test_argument_provenance_survives_source_and_query_roundtrip():
    graph = graph_for('python', 'alias')
    before = graph.to_dict()
    restored_source = IR.from_dict(json.loads(json.dumps(before)))
    assert restored_source.to_dict() == before
    assert producers_at_take(restored_source) == {0}
    view = query_graph(graph).ir
    restored = IR.from_dict(json.loads(json.dumps(view.to_dict())))
    restored_result = evaluate_query(restored, QUERY)
    original_result = evaluate_query(view, QUERY)
    assert restored_result['complete'] and original_result['complete']
    assert restored_result['matches'] == original_result['matches']
    assert graph.to_dict() == before


@pytest.mark.parametrize('language', LANGUAGES)
def test_positions_and_repeated_reads_do_not_mix_origins(language):
    text = source(language, 'alias').replace('take(n)', 'take(n, m)').replace('take(int n)', 'take(int n, int m)')
    text = text.replace('take(saved)', 'take(saved, x)')
    graph = link_project([lower_source(text, language, 'positions')])
    assert not graph.diagnostics
    calls = sorted((e for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'make'),
                   key=lambda e: e.attrs['start_byte'])
    take = next(e.id for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'take')
    evidence = sorted((f for f in graph.facts if f.relation == 'ARGUMENT_ORIGIN' and f.subject == take),
                      key=lambda f: f.attrs['position'])
    assert [f.attrs['position'] for f in evidence] == [0, 1]
    assert [f.attrs['origins'] for f in evidence] == [[calls[0].id], [calls[1].id]]
    assert all(f.attrs['modality'] == 'must' for f in evidence)
    view = query_graph(graph).ir
    for position, call in enumerate(calls):
        loaded = take+f'/argument/{position}/loaded-value'
        must = [f.subject for f in view.facts if f.relation == 'VALUE_FLOW' and f.object == loaded
                and f.attrs.get('modality') == 'must']
        assert must == [call.id+'/result']


@pytest.mark.parametrize('language', LANGUAGES)
def test_each_consumer_snapshots_before_the_next_write(language):
    text = source(language, 'overwrite').replace('x=make(2)', 'take(x)\n x=make(2)' if language == 'python'
                                               else 'take(x);x=make(2)')
    graph = link_project([lower_source(text, language, 'reads')])
    calls = sorted((e for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'make'),
                   key=lambda e: e.attrs['start_byte'])
    consumers = sorted((e for e in graph.entities.values() if e.kind == 'CALL' and e.attrs.get('name') == 'take'),
                       key=lambda e: e.attrs['start_byte'])
    assert len(calls) == len(consumers) == 2
    for call, consumer in zip(calls, consumers, strict=True):
        facts = [f for f in graph.facts if f.relation == 'ARGUMENT_ORIGIN' and f.subject == consumer.id]
        assert len(facts) == 1
        assert facts[0].attrs['origins'] == [call.id]
        assert facts[0].attrs['modality'] == 'must'


def test_unmodeled_loop_keeps_argument_provenance_conservative():
    graph = link_project([lower_source('''def run(flag):
 x=make()
 while flag:
  take(x)
 return 0
''', 'python', 'loop.py')])
    assert any(f.relation == 'RETURN_FLOW_STATUS' and f.object == 'unsupported' for f in graph.facts)
    result = evaluate_query(graph, QUERY)
    assert result['complete']
    assert not result['matches']
