"""Audit a closed CORE run without changing its scorer, labels, or search outputs."""
from pathlib import Path
import ast
import collections
import hashlib
import json
import math
import sys

w = Path.cwd()
sys.path.insert(0, str(w / 'experiments/search-engine'))
from grade_public_v224 import load_closed_results
from public_benchmarks_v222 import sha

out = w / 'output/development/repoqa-core-v222'
dest = w / 'output/analysis/core-pilot-audit-v227'
dest.mkdir(exist_ok=False)
registration = json.loads((out / 'core-registration.json').read_text())
assert sha(out / 'core-sources.json') == registration['sources_sha256']
assert sha(out / 'core-document-map.json') == registration['document_map_sha256']
assert sha(out / 'core-requests.jsonl') == registration['requests_sha256']
requests = [json.loads(line) for line in (out / 'core-requests.jsonl').read_text().splitlines()]
sources = json.loads((out / 'core-sources.json').read_text())
maps = json.loads((out / 'core-document-map.json').read_text())
responses = load_closed_results(out / 'core-capture-v224', [r['id'] for r in requests])
original = json.loads((out / 'core-report-v224.json').read_text())
original_rows = {r['id']: r for r in original['rows']}
official_file = Path('/private/tmp/ken-core-public-v222/collect_results/collect_core_bench_results.py')
node = next(n for n in ast.parse(official_file.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name == 'calculate_metrics')
environment = {'math': math, 'Dict': dict, 'Set': set, 'KS': [10]}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(official_file), 'exec'), environment)
official_metrics = environment['calculate_metrics']

def normalized(text):
    return text.replace('\r\n', '\n').strip()

def parsed(text):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None

def callable_hashes(text):
    tree = parsed(text)
    if tree is None:
        return set()
    return {hashlib.sha256(ast.dump(n, include_attributes=False).encode()).hexdigest()
            for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

raw_cache, rows = {}, []
mapping_checks = 0
evidence_checks = 0
for request in requests:
    snapshot = sources[request['repo_id']]
    raw_folder = Path(snapshot['raw_folder'])
    if str(raw_folder) not in raw_cache:
        for name in ['corpus.jsonl', 'queries.jsonl', 'qrels.jsonl']:
            p = raw_folder / name
            assert sha(p) == registration['raw_file_pins'][p.relative_to(out / 'core-raw').as_posix()]
        docs = {r['_id']: r['text'] for r in map(json.loads, (raw_folder / 'corpus.jsonl').read_text().splitlines())}
        qrels = collections.defaultdict(set)
        for relation in map(json.loads, (raw_folder / 'qrels.jsonl').read_text().splitlines()):
            assert relation['score'] == 1
            qrels[relation['query_id']].add(relation['corpus_id'])
        raw_cache[str(raw_folder)] = docs, qrels
    docs, qrels = raw_cache[str(raw_folder)]
    expected = qrels[snapshot['public_query_id']]
    mapping = maps[request['repo_id']]
    assert expected <= set(mapping.values())
    response = responses[request['id']]
    results = response.get('results', [])
    order = []
    for result in results:
        doc_id = mapping[result['path']]
        body = docs[doc_id]
        data = body.encode('utf-8')
        expected_hash = hashlib.sha256(data).hexdigest()
        assert (Path(request['root']) / result['path']).read_bytes() == data
        assert result['source_hash'] == snapshot['source_pins'][result['path']] == expected_hash
        assert not result.get('stale')
        for fragment in result['evidence']:
            assert fragment['content'] == '\n'.join(body.splitlines()[fragment['start_line']-1:fragment['end_line']])
            evidence_checks += 1
        order.append(doc_id)
        mapping_checks += 1
    old = original_rows[request['id']]
    assert order == old['order']
    metrics = official_metrics({doc: float(100 - i) for i, doc in enumerate(order)}, expected)
    assert metrics['hit@10'] == old['hit10']
    assert abs(metrics['recall@10'] - old['recall10']) < 1e-12
    assert abs(metrics['ndcg@10'] - old['ndcg10']) < 1e-12
    assert int(bool(order and order[0] in expected)) == old['hit1']
    exact = {docs[identifier] for identifier in expected}
    normal = {normalized(text) for text in exact}
    gold_callables = set().union(*(callable_hashes(text) for text in exact))
    byte_aliases = [i + 1 for i, doc in enumerate(order) if docs[doc] in exact]
    normalized_aliases = [i + 1 for i, doc in enumerate(order) if normalized(docs[doc]) in normal]
    function_overlap = [i + 1 for i, doc in enumerate(order)
                        if callable_hashes(docs[doc]) & gold_callables]
    row = {'id': request['id'], 'repo': snapshot['repo'], 'level': snapshot['level'],
        'query_id': snapshot['public_query_id'], 'title': request['query'].splitlines()[0],
        'query_chars': len(request['query']), 'error': response.get('error'),
        'results': len(results), 'gold_documents': len(expected),
        'hit1': old['hit1'], 'hit10': old['hit10'], 'ndcg10': old['ndcg10'],
        'byte_equal_relevant_ranks': byte_aliases, 'normalized_equal_relevant_ranks': normalized_aliases,
        'complete_callable_AST_overlap_ranks': function_overlap,
        'top1_id': order[0] if order else None,
        'top1_header': next((line for line in docs[order[0]].splitlines() if line.strip()), '')[:200] if order else None,
        'expected_headers': [next((line for line in docs[g].splitlines() if line.strip()), '')[:160]
                             for g in sorted(expected)],
        'raw_source': str(raw_folder)}
    rows.append(row)

summary = {'closed_cases': len(rows), 'returned_document_mappings_verified': mapping_checks,
    'faithful_visible_fragments_verified': evidence_checks, 'official_metric_mismatches': 0,
    'response_compact_string_used_by_scorer': False,
    'official_hit1': sum(r['hit1'] for r in rows), 'official_hit10': sum(r['hit10'] for r in rows),
    'byte_equal_hit1': sum(1 in r['byte_equal_relevant_ranks'] for r in rows),
    'byte_equal_hit10': sum(bool(r['byte_equal_relevant_ranks']) for r in rows),
    'normalized_equal_hit1': sum(1 in r['normalized_equal_relevant_ranks'] for r in rows),
    'normalized_equal_hit10': sum(bool(r['normalized_equal_relevant_ranks']) for r in rows),
    'complete_callable_AST_overlap_hit1': sum(1 in r['complete_callable_AST_overlap_ranks'] for r in rows),
    'complete_callable_AST_overlap_hit10': sum(bool(r['complete_callable_AST_overlap_ranks']) for r in rows),
    'callable_overlap_is_only_diagnostic_not_equivalence_or_official_score': True,
    'errors': sum(bool(r['error']) for r in rows),
    'official_collector_sha256': sha(official_file),
    'original_report_sha256': sha(out / 'core-report-v224.json'),
    'audit_script_sha256': sha(Path(__file__)), 'engine_modified': False,
    'reserve': 'CLOSED'}
(dest / 'audit.json').write_text(json.dumps({'summary': summary, 'rows': rows}, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(summary, ensure_ascii=False))
for row in rows:
    print(json.dumps({k: row[k] for k in ['query_id', 'level', 'title', 'hit1', 'hit10', 'error', 'top1_header',
                     'byte_equal_relevant_ranks', 'normalized_equal_relevant_ranks', 'complete_callable_AST_overlap_ranks']}, ensure_ascii=False))
