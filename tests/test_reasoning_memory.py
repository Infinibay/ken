from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random

import pytest

from ken.reasoning.arithmetic import calculate
from ken.reasoning.kernel import Kernel
from ken.reasoning.model import Atom, builtin_rules, digest, unify
from ken.reasoning.store import Memory


def a(p, s='x', o='yes', negative=False, scope='present'):
    return Atom(p, s, o, negative, scope).data()


def r(body, head):
    return {'body': body, 'head': head}


@pytest.fixture
def memory(tmp_path):
    return Memory(tmp_path / 'reasoning.sqlite')


def test_reuse_restart_and_unrelated_query(memory):
    memory.record('doc', facts=[a('type', 'Atlas', 'robot'), a('subclass', 'robot', 'machine'),
                                a('all/use', 'machine', 'battery')], evidence='source revision 1')
    q = a('use', 'Atlas', 'battery')
    first = memory.ask(q)
    assert first['status'] == 'supported' and first['metrics']['complete']
    reopened = Memory(memory.path).ask(q)
    assert reopened['metrics']['work'] == 0
    assert reopened['answers'] == first['answers']
    assert reopened['sources'] == {'doc': 'source revision 1'}
    assert memory.ask(a('type', 'Atlas', 'machine'))['metrics']['work'] == 0


def test_append_delta_does_not_expand_old_facts(memory):
    memory.record('a', facts=[a('p')], rules=[r([a('p', '?x')], a('q', '?x'))])
    initial = memory.ask(a('q'))
    memory.record('b', facts=[a('p', 'y')])
    appended = memory.ask(a('q', 'y'))
    assert appended['status'] == 'supported' and appended['reuse']['checkpoint']
    assert appended['metrics']['work'] == initial['metrics']['work']
    assert appended['metrics']['facts'] == 4


def test_new_negative_invalidates_status_without_erasing_positive(memory):
    memory.record('a', facts=[a('p')])
    assert memory.ask(a('p'))['status'] == 'supported'
    memory.record('b', facts=[a('p', negative=True)])
    assert memory.ask(a('p'))['status'] == 'conflict'


def test_empty_and_wh_queries_notice_new_data(memory):
    assert memory.ask(a('p'))['status'] == 'unknown'
    memory.record('a', facts=[a('p')])
    assert memory.ask(a('p'))['status'] == 'supported'
    memory.record('b', facts=[a('p', 'y')])
    assert len(memory.ask(a('p', '?who'))['answers']) == 2


def test_retraction_alternate_support_and_cycles(memory):
    memory.record('rules', rules=[r([a('p')], a('q')), r([a('q')], a('p'))])
    memory.record('a', facts=[a('p')])
    memory.record('b', facts=[a('p')])
    assert memory.ask(a('q'))['status'] == 'supported'
    memory.record('a', retract=True)
    assert memory.ask(a('q'))['status'] == 'supported'
    memory.record('b', retract=True)
    out = memory.ask(a('q'))
    assert out['status'] == 'unknown' and out['metrics']['facts'] == 0


def test_source_replacement_and_rule_replacement(memory):
    memory.record('a', facts=[a('p')], rules=[r([a('p')], a('q'))])
    assert memory.ask(a('q'))['status'] == 'supported'
    memory.record('a', facts=[a('p')], rules=[r([a('p')], a('z'))])
    assert memory.ask(a('q'))['status'] == 'unknown'
    assert memory.ask(a('z'))['status'] == 'supported'


def test_world_context_and_time_isolation(memory):
    memory.record('a', facts=[a('p')], context='one')
    assert memory.ask(a('p'), context='two')['status'] == 'unknown'
    assert memory.ask(a('p', scope='past'), context='one')['status'] == 'unknown'
    out = memory.ask(a('p'), context='one', assumptions=[a('p', negative=True)])
    assert out['status'] == 'conflict'
    assert memory.ask(a('p'), context='one')['status'] == 'supported'
    assert memory.ask(a('q'), assumptions=[a('q')])['status'] == 'supported'
    assert memory.ask(a('q'))['status'] == 'unknown'


def test_assumption_world_inherits_closed_base(memory):
    memory.record('a', facts=[a('p')], rules=[r([a('p', '?x')], a('q', '?x'))])
    base = memory.ask(a('q'))
    overlay = memory.ask(a('q', 'y'), assumptions=[a('p', 'y')])
    assert overlay['status'] == 'supported'
    assert overlay['reuse']['prior_facts'] == base['metrics']['facts']
    assert overlay['answers'][0]['proof']['premises'][0]['support']['kind'] == 'assumption'


def test_invalid_bundle_atomic_and_idempotent(memory):
    memory.record('a', facts=[a('p')])
    assert not memory.record('a', facts=[a('p')])['changed']
    with pytest.raises(ValueError):
        memory.record('a', facts=[a('q'), a('bad', '?x')])
    assert memory.ask(a('p'))['status'] == 'supported'
    assert memory.ask(a('q'))['status'] == 'unknown'


@pytest.mark.parametrize('seed', range(6))
def test_resume_mid_join_matches_uninterrupted_and_naive(tmp_path, seed):
    rng = random.Random(seed)
    facts = [a(rng.choice(['p', 'q']), rng.choice(['a', 'b', 'c']), rng.choice(['a', 'b', 'c'])) for _ in range(15)]
    rules = [r([a('p', '?x', '?y'), a('q', '?y', '?z'), a('p', '?z', '?w')], a('joined', '?x', '?w')),
             r([a('q', '?x', '?y')], a('p', '?x', '?y')),
             r([a('p', '?x', '?y')], a('q', '?x', '?y'))]
    known = {Atom.read(f) for f in facts}
    while True:
        added = set()
        for rule in rules:
            bindings = [{}]
            for p in rule['body']:
                bindings = [b for prior in bindings for f in known
                            if (b := unify(Atom.read(p), f, prior)) is not None]
            added.update(Atom.read(rule['head']).bind(b) for b in bindings)
        if added <= known:
            break
        known |= added
    full = Memory(tmp_path / 'full.sqlite')
    resumed = Memory(tmp_path / 'resumed.sqlite')
    for m in (full, resumed): m.record('source', facts=facts, rules=rules)
    goal = a('joined', '?x', '?y')
    original = full.ask(goal, seed=seed, budget=10000)
    for _ in range(3000):
        out = Memory(resumed.path).ask(goal, seed=seed, budget=3)
        if out['metrics']['complete']: break
    assert out['metrics']['complete'] and original['metrics']['complete']
    assert out['metrics']['total_work'] == original['metrics']['total_work']
    assert out['answers'] == original['answers']
    with resumed.connection() as db:
        state = json.loads(db.execute('SELECT state FROM checkpoints').fetchone()[0])
    assert {Atom.read(v['atom']) for v in state['facts'].values()} == known


def test_concurrent_requests_do_not_lose_events_or_progress(memory):
    def job(i):
        m = Memory(memory.path)
        m.record(str(i), facts=[a('p', str(i))])
        return m.ask(a('p', '?x'), budget=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(job, range(8)))
    assert len(memory.ask(a('p', '?x'))['answers']) == 8


def test_missing_conditions_are_not_promoted(memory):
    memory.record('r', rules=[r([a('p')], a('q'))])
    out = memory.ask(a('q'))
    assert out['status'] == 'unknown'
    assert out['approximation'][0]['required'] == [a('p')]
    assert not out['approximation'][0]['promoted']
    assert memory.ask(a('q'), assumptions=[a('p')])['status'] == 'supported'
    assert memory.ask(a('q'))['status'] == 'unknown'


@pytest.mark.parametrize('expr', ['__import__("os")', 'x + 1', '1/0', '2**999', '1e999999999',
                                 '[1,2]', 'True', '1 << 2', '10**(10**10)'])
def test_calculator_rejects_code_and_unbounded_operations(expr):
    with pytest.raises(ValueError): calculate(expr)


def test_exact_calculation():
    assert calculate('0.1 + 0.2')['exact'] == '3/10'
    assert calculate('(3/4)*8')['exact'] == '6'


def test_mcp_and_cli_registry(tmp_path, monkeypatch):
    from ken.mcp import server
    monkeypatch.setattr(server, '_PROJECT_ROOT', tmp_path)
    assert {'ken_reason', 'ken_reason_record', 'ken_calculate'} <= {t.name for t in server.list_tools()}
    record_tool = next(t for t in server.list_tools() if t.name == 'ken_reason_record')
    assert record_tool.parameters['properties']['facts']['items'] == {'type': 'object'}
    assert server.ken_reason_record('s', facts=[a('p')])['changed']
    assert server.ken_reason('P?', goal=a('p'))['status'] == 'supported'
    assert server.ken_reason('P?', goal=a('p'))['metrics']['work'] == 0
    assert server.ken_calculate('1/3')['exact'] == '1/3'
    monkeypatch.setattr(server, 'ken_recall', lambda **kwargs: [{'content': 'unverified note'}])
    out = server.ken_reason('What do we know?')
    assert out['status'] == 'needs_interpretation' and 'answers' not in out


def test_cli_decodes_goal_and_premise_objects(tmp_path, capsys):
    from ken.cli import main
    (tmp_path / '.ken').mkdir()
    (tmp_path / '.ken/meta.json').write_text('{}')
    prefix = ['tools', '--path', str(tmp_path)]
    assert main(prefix + ['reason_record', 's', '--facts', json.dumps(a('p'))]) == 0
    assert json.loads(capsys.readouterr().out)['changed']
    assert main(prefix + ['reason', 'P?', '--goal', json.dumps(a('p'))]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'supported'
    assert main(prefix + ['reason', 'Q?', '--goal', json.dumps(a('q')),
                          '--assumptions', json.dumps(a('q'))]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'supported'


@pytest.mark.parametrize('bad', ['[1,2]', '{broken', 'null', '"text"'])
def test_cli_rejects_invalid_object_values(tmp_path, bad):
    from ken.cli import _build_tool_parser
    from ken.mcp.server import list_tools
    parser = _build_tool_parser(next(t for t in list_tools() if t.name == 'ken_reason'))
    with pytest.raises(SystemExit): parser.parse_args(['P?', '--goal', bad])
