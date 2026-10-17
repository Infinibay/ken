"""Combine separately tested pure symbol-order policies on actual201MCP pools."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0, str(Path.cwd() / 'experiments/search-engine'))
from ken.retrieval.source_operations import OperationWitnesses
from ken.retrieval.symbol_requirements import requested_operations, prefer_operations, requests_test_case, is_test_case
from ken.retrieval.symbol_requirements import explicit_code_terms, prefer_explicit_code_terms

from ken.retrieval.candidates import owner_passages
from ken.retrieval.connections import project_connection
from ken.retrieval.description import describe_owner

from ken.retrieval.intent import requested_piece_path
from ken.retrieval.model import EntityKey, SearchRequest
from ken.retrieval.piece_catalog import SourceCatalog


def prefer_requested_test_piece(query, units, catalog):
    order=list(range(len(units)))
    if requests_test_case(SearchRequest(query)):
        order.sort(key=lambda i:not is_test_case(EntityKey(path=units[i]['path'],**units[i]['entity']),catalog))
    return order


def composition_orders(card, code, native):
    import numpy as np
    stable=sorted(range(len(card)),key=lambda i:native[i])
    means=[(a+b)/2 for a,b in zip(card,code,strict=True)]
    card_order=sorted(stable,key=lambda i:-card[i]);code_order=sorted(stable,key=lambda i:-code[i])
    a_rank={i:r for r,i in enumerate(card_order,1)};b_rank={i:r for r,i in enumerate(code_order,1)}
    fused=[1/(60+a_rank[i])+1/(60+b_rank[i]) for i in range(len(card))]
    a=np.asarray(card);b=np.asarray(code);standardized=(a-a.mean())/(a.std() or 1)+(b-b.mean())/(b.std() or 1)
    return {'baseline_mean':sorted(stable,key=lambda i:-means[i]),'code_only':code_order,
        'rank_fusion':sorted(stable,key=lambda i:-fused[i]),'standardized_mean':sorted(stable,key=lambda i:-standardized[i])}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


w = Path.cwd()
scope_path = w / 'output/analysis/english-ranking-v196/registration.json'
scope = json.loads(scope_path.read_text())
cases, answers = {}, {}
pins = {}
for cohort, selection in scope['cohorts'].items():
    path = Path(selection['english_cases'])
    assert sha(path) == selection['sha256']
    cases.update({row['id']: row | {'cohort': cohort} for row in rows(path)})
    root = w / 'output/development' / ('public-requested-test-role-v201-' + cohort)
    lock = json.loads((root / 'lock.json').read_text())
    reg = json.loads((root / 'capture/registration.json').read_text())
    assert reg['status'] == lock['closed_status']
    pins[cohort] = sha(root / 'capture/registration.json')
    for repo, files in reg['closed'].items():
        path = root / 'capture' / repo / 'answers.jsonl'
        assert sha(path) == files['answers.jsonl']
        answers.update({row['id']: row for row in rows(path) if row['id'] in cases})
assert len(cases) == len(answers) == 240 and set(cases) == set(answers)
score_root = w / 'output/development/current-symbol-scores-v207'
score_reg = json.loads((score_root / 'registration.json').read_text())
assert score_reg['status'] == 'ALL150currentEnglishsymbol scores CLOSED without Gold'
assert sha(score_root / 'scores.jsonl') == score_reg['scores_sha256']
score_records = {row['id']: row for row in rows(score_root / 'scores.jsonl')}
assert len(score_records) == 150
views_root = w / 'output/development/current-executable-view-v209'
views_reg = json.loads((views_root / 'registration.json').read_text())
assert views_reg['status'] == 'ALL128currentEnglish executable view scores CLOSED before Gold'
view_records = {}
for repo, digests in views_reg['closed'].items():
    path = views_root / repo / 'observations.jsonl'
    assert sha(path) == digests['observations.jsonl']
    view_records.update({row['id']: row for row in rows(path)})
assert len(view_records) == 128
out = w / 'output/analysis/view-scale-v288-old240'
out.mkdir(exist_ok=False)
protocol = {
    'scope': 'English240 EXPOSED development on ACTUAL201pools, authenticated207NN1024scalars:122guarded source/query/card identical reuses plus6freshAPI and22exact. No inference or model changes. Reserve CLOSED.',
    'hypothesis': 'Actual source-card and complete-code views use the same model but their raw-logit scales need not be interchangeable. Compare unchanged equal mean with code-only, fixed k60 rank fusion and within-query standardized mean. All prior source constraints/paths/exact bypass and budgets unchanged. No learned parameters or per-language/repository routing. Pure already-closed-logit diagnostic; no model inference or blind acceptance.',
    'variants': ['baseline_mean','code_only','rank_fusion','standardized_mean'],
    'policy': 'Actual201 answers stay fixed for non-symbols and unique exact bypass. Raw neural order preserves native ties; requested test-case preference then literal-operator preference. Always retain namedpath priority and all candidate identities. No fitted weights/IDs/names of repositories.',
    'acceptance': '>=108/120EACH;118/119Recall10; all refs unchanged. Results are pure policy replay, not full combined MCP latency/acceptance.',
    'producer_sha256': sha(Path(__file__)), 'selection_sha256': sha(scope_path), 'capture_pins': pins,
    'score_receipt_sha256': sha(score_root / 'registration.json'),
    'view_receipt_sha256': sha(views_root / 'registration.json'),
    'policy_sources': {name: sha(Path('/Users/andres/.codex/worktrees/compact-default-output/ken/src/ken/retrieval') / name) for name in ['symbol_requirements.py','source_operations.py','description.py','piece_catalog.py','intent.py']},
    'status': 'Registered BEFORE orders and Gold',
}
(out / 'registration.json').write_text(json.dumps(protocol, indent=2))
predictions = []
witness_records = []
budget_records = []
previous_budget_root=w/'output/development/bounded-operation-policies-v213'
previous_budget_reg=json.loads((previous_budget_root/'registration.json').read_text())
assert sha(previous_budget_root/'budgets.jsonl')==previous_budget_reg['budgets_sha256']
previous_budgets={(r['id'],json.dumps(r['unit'],sort_keys=True)):r for r in rows(previous_budget_root/'budgets.jsonl')}
for repo in sorted({row['repo_id'] for row in cases.values()}):
    selected = [case for case in cases.values() if case['repo_id'] == repo]
    symbol_cases = [case for case in selected if case['target_kind'] == 'symbol' and
                    answers[case['id']]['public_response']['profile_version'] != 'best-exact-source-v1']
    paths = {unit['path'] for case in symbol_cases for unit in answers[case['id']]['units']}
    catalog = None
    relations = None
    if paths:
        root = Path('/private/tmp/ken-public-default-v143/repos') / repo
        with project_connection(root) as connection:
            connection.execute('PRAGMA query_only=ON')
            catalog = SourceCatalog(root, {key: ps for key, ps in owner_passages(connection).items() if key.path in paths})
            relations = OperationWitnesses(catalog)
    for case in selected:
        query_id = case['id']
        answer = answers[query_id]
        units = answer['units']
        orders = {name: units for name in protocol['variants']}
        if case in symbol_cases:
            assert catalog is not None
            results = answer['public_response']['results']
            assert len(results) == len(units)
            scored = score_records[query_id]
            assert not scored['exact_bypass'] and scored['units'] == units
            signals = scored['score_rows']
            assert [row['unit'] for row in signals] == units
            assert sorted(signal['native_rank'] for signal in signals) == list(range(1, len(units)+1))
            raw = sorted(range(len(units)), key=lambda i: (-signals[i]['neural_score'], signals[i]['native_rank']))
            neural_units = [units[i] for i in raw]
            view = view_records[query_id]
            assert view['units'] == units
            assert view['original_input_hashes'] == [row['input_sha256'] for row in signals]
            code_scores = list(view['executable_scores'])
            for index, unit in enumerate(units):
                key = EntityKey(path=unit['path'], **unit['entity'])
                description = describe_owner(catalog.owners[key])
                full = '\n'.join([f'symbol {key.path} {key.qualname}', description.fields['signature'], 'Implementation:', description.fields['executable']])
                old_budget=previous_budgets[(query_id,json.dumps(unit,sort_keys=True))]
                length=old_budget['full_pair_tokens']
                assert len(full)==old_budget['full_chars']
                accepted = (len(description.fields['executable'].splitlines()) <= 64 and len(full) <= 12000 and length <= 1024)
                if accepted:
                    assert full == view['texts'][index]
                else:
                    code_scores[index] = signals[index]['neural_score']
                budget_records.append({'id': query_id, 'unit': unit, 'full_pair_tokens': length,
                    'complete_owned_lines': len(description.fields['executable'].splitlines()), 'full_chars': len(full),
                    'accepted_complete_code_view': accepted})
            means = [(s['neural_score'] + score) / 2 for s, score in zip(signals, code_scores, strict=True)]
            mean_order = sorted(range(len(units)), key=lambda i: (-means[i], signals[i]['native_rank']))
            mean_units = [units[i] for i in mean_order]
            requested = requested_operations(case['query'])
            observed = [relations.for_owner(EntityKey(path=unit['path'], **unit['entity'])) for unit in units]
            lookup = {json.dumps(unit, sort_keys=True): value for unit, value in zip(units, observed, strict=True)}
            witness_records.append({'id': query_id, 'query': case['query'], 'requested': sorted(requested),
                'units': units, 'observed': [sorted(value) for value in observed],
                'source_hashes': [catalog.hashes[unit['path']] for unit in units]})
            for name,indices in composition_orders([r['neural_score'] for r in signals],code_scores,[r['native_rank'] for r in signals]).items():
                base=[units[i] for i in indices];allowed=requested
                facts = [lookup[json.dumps(unit, sort_keys=True)] for unit in base]
                base = [base[i] for i in prefer_operations(allowed, facts, list(range(len(base))))]
                orders[name] = [base[i] for i in prefer_requested_test_piece(case['query'], base, catalog)]
            for name in protocol['variants']:
                base = orders[name]
                implementations = []
                if explicit_code_terms(case['query']):
                    for unit in base:
                        key = EntityKey(path=unit['path'], **unit['entity'])
                        implementations.append(describe_owner(catalog.owners[key]).fields['executable'])
                else:
                    implementations = [''] * len(base)
                order = prefer_explicit_code_terms(case['query'], implementations, list(range(len(base))))
                orders[name] = [base[i] for i in order]
            named = requested_piece_path(SearchRequest(case['query']))
            if named:
                for result in orders.values():
                    result.sort(key=lambda unit: unit['path'] != named)
        canonical = lambda unit: json.dumps(unit, sort_keys=True)
        assert all(sorted(map(canonical, result)) == sorted(map(canonical, units)) for result in orders.values())
        predictions.append({name: case[name] for name in ['id', 'cohort', 'language', 'target_kind', 'repo_id']} | {'orders': orders})
# Before any new grading, reproduce every old production first-to-tenth identity.
actual={}
for cohort in ('original','symbols'):
    historical=w/f'output/development/public-bounded-symbol-ranking-v214-{cohort}'
    registration=json.loads((historical/'capture/registration.json').read_text())
    for repo,digests in registration['closed'].items():
        path=historical/'capture'/repo/'answers.jsonl';assert sha(path)==digests['answers.jsonl']
        actual.update({r['id']:r['units'] for r in rows(path) if r['id'] in cases})
assert len(actual)==240
for prediction in predictions:assert prediction['orders']['baseline_mean']==actual[prediction['id']],('baseline order differs',prediction['id'])
protocol['old240_baseline_orders_reproduced']=True
protocol['no_model_inference']=True
(out / 'budgets.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in budget_records))
(out / 'witnesses.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in witness_records))
(out / 'predictions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in predictions))
protocol.update(status='ALL240English variant orders CLOSED before exposed Gold', predictions_sha256=sha(out / 'predictions.jsonl'), witnesses_sha256=sha(out / 'witnesses.jsonl'), budgets_sha256=sha(out / 'budgets.jsonl'))
(out / 'registration.json').write_text(json.dumps(protocol, indent=2))
print(json.dumps({'closed': len(predictions), 'variants': protocol['variants']}))
