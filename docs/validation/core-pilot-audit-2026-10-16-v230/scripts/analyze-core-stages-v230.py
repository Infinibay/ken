"""Join reference labels only after verifying the closed diagnostic captures."""
from collections import Counter
from pathlib import Path
import hashlib
import json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


w = Path.cwd()
base = w / 'output/development/repoqa-core-v222'
stages = w / 'output/analysis/core-stages-v228'
dest = w / 'output/analysis/core-stage-analysis-v230'
dest.mkdir(exist_ok=False)
closure = json.loads((stages / 'closure.json').read_text())
assert closure['queries'] == 18 and closure['all_original_orders_or_errors_reproduced']
for name, digest in closure['pins'].items():
    assert sha(stages / name) == digest
registration = json.loads((base / 'core-registration.json').read_text())
for name, key in [('core-sources.json', 'sources_sha256'), ('core-document-map.json', 'document_map_sha256')]:
    assert sha(base / name) == registration[key]
sources = json.loads((base / 'core-sources.json').read_text())
maps = json.loads((base / 'core-document-map.json').read_text())
audit_path = w / 'output/analysis/core-pilot-audit-v227/audit.json'
audit = json.loads(audit_path.read_text())
rows, fusion_rows = [], []
for audited in audit['rows']:
    stage = json.loads((stages / (audited['id'] + '.json')).read_text())
    source = sources[stage['repo_id']]
    raw_qrels = Path(source['raw_folder']) / 'qrels.jsonl'
    assert sha(raw_qrels) == registration['raw_file_pins'][raw_qrels.relative_to(base / 'core-raw').as_posix()]
    mapping = maps[stage['repo_id']]
    gold = {r['corpus_id'] for r in map(json.loads, raw_qrels.read_text().splitlines())
            if r['query_id'] == audited['query_id'] and r['score'] > 0}
    def relevant_ranks(paths):
        return [i + 1 for i, path in enumerate(paths) if mapping[path] in gold]
    response = stage.get('diagnostic_response', {})
    results = response.get('results', [])
    ranks = {'proposals': relevant_ranks([p['path'] for p in stage['proposals']]),
             'numeric': relevant_ranks([p['path'] for p in stage['numeric_order']]),
             'native': relevant_ranks(stage['native_piece_paths']),
             'final': relevant_ranks([r['path'] for r in results])}
    assert ranks['final'] == audited['normalized_equal_relevant_ranks']
    assert bool(stage.get('diagnostic_error')) == bool(audited['error'])
    rows.append({'id': audited['id'], 'query_id': audited['query_id'], 'level': audited['level'],
                 'purpose': stage['inferred_purpose'], 'error': audited['error'],
                 'gold_documents': len(gold), 'rank': ranks, 'source_summary': stage['source_summary']})
    if not results:
        continue
    ordered = sorted(results, key=lambda r: r['signals']['piece_rank'])
    neural = sorted(ordered, key=lambda r: (-r['signals']['neural_score'], r['signals']['piece_rank']))
    positions = {r['path']: i + 1 for i, r in enumerate(neural)}
    def explain(result):
        signals = result['signals']
        nr = positions[result['path']]
        return {'path': result['path'], 'relevant': mapping[result['path']] in gold,
                'native_rank': signals['native_piece_rank'], 'piece_rank': signals['piece_rank'],
                'neural_rank': nr, 'neural_score': signals['neural_score'],
                'fusion_score': .5 / (60 + signals['piece_rank']) + .5 / (60 + nr)}
    fusion = [explain(r) for r in results]
    assert [r['path'] for r in sorted(fusion, key=lambda r: (-r['fusion_score'], r['piece_rank']))] == [r['path'] for r in results]
    fusion_rows.append({'id': audited['id'], 'query_id': audited['query_id'], 'level': audited['level'],
        'native_hit1': 1 in ranks['native'], 'piece_hit1': mapping[ordered[0]['path']] in gold,
        'neural_hit1': mapping[neural[0]['path']] in gold, 'final_hit1': mapping[results[0]['path']] in gold,
        'candidates': fusion})
assert len(rows) == 18 and len(fusion_rows) == 16
summary = {'queries': len(rows), 'purpose': dict(Counter(r['purpose'] for r in rows)),
    'all_symbols_zero': all(r['source_summary']['symbol_count'] == 0 for r in rows),
    'all_passages_documentation': all(set(r['source_summary']['roles']) == {'documentation'} for r in rows),
    'all_signatures_empty': all(r['source_summary']['empty_signature_passages'] == r['source_summary']['passages'] for r in rows),
    'all_documentation_fields_empty': all(r['source_summary']['empty_documentation_passages'] == r['source_summary']['passages'] for r in rows),
    'stage_hits': {stage: {'hit1': sum(1 in r['rank'][stage] for r in rows),
        'hit10': sum(any(i <= 10 for i in r['rank'][stage]) for r in rows),
        'any': sum(bool(r['rank'][stage]) for r in rows)} for stage in ['proposals', 'numeric', 'native', 'final']},
    'fusion_completed_queries': len(fusion_rows),
    'fusion_hit1': {key: sum(r[key] for r in fusion_rows)
                    for key in ['native_hit1', 'piece_hit1', 'neural_hit1', 'final_hit1']},
    'ranking_only_counterfactuals_are_not_new_acceptance_scores': True,
    'all_existing_fusion_orders_reproduced': True,
    'inputs': {'audit_sha256': sha(audit_path), 'stage_closure_sha256': sha(stages / 'closure.json'),
               'core_sources_sha256': sha(base / 'core-sources.json'), 'script_sha256': sha(Path(__file__))},
    'reserve': 'CLOSED'}
(dest / 'analysis.json').write_text(json.dumps({'summary': summary, 'rows': rows, 'fusion_rows': fusion_rows}, indent=2) + '\n')
print(json.dumps(summary, indent=2))
