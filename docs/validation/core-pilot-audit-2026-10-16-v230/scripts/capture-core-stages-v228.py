"""Replay closed public inputs through frozen stages; no relevance labels enter."""
from pathlib import Path
from dataclasses import replace
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
import resource
import sys

w = Path.cwd()
out = w / 'output/development/repoqa-core-v222'
dest = w / 'output/analysis/core-stages-v228'
dest.mkdir(exist_ok=False)
registration = json.loads((out / 'registration.json').read_text())
engine = Path(registration['engine'])
sys.path.insert(0, str(engine / 'src'))
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
assert sha(engine / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256']
for name, digest in json.loads((engine / 'SOURCE-MANIFEST.json').read_text())['files'].items():
    assert sha(engine / name) == digest
import ken
assert Path(ken.__file__).resolve().parents[2] == engine
from ken.retrieval.best_search import _prepared
from ken.retrieval.best_resources import default_resources
from ken.retrieval.candidates import owner_passages, owner_descriptions, retrieve_contextual
from ken.retrieval.connections import project_connection
from ken.retrieval.intent import interpret
from ken.retrieval.model import SearchRequest
from ken.retrieval.piece_cards import build_piece_cards
from ken.retrieval.ranking_trace import RankingTrace

requests = [json.loads(line) for line in (out / 'core-requests.jsonl').read_text().splitlines()]
assert len(requests) == 18
resources = default_resources()
pins = {}
for public in requests:
    root = Path(public['root'])
    original = json.loads((out / 'core-capture-v224' / public['repo_id'] / 'responses.json').read_text())[0]
    assert original['id'] == public['id']
    request = SearchRequest(public['query'], target='file', piece_kind='file')
    with project_connection(root) as conn:
        project = _prepared(conn, root, resources)
        owners = owner_passages(conn)
        descriptions = [p.fields for ps in owners.values() for p in ps]
        summary = {'owners': len(owners), 'kinds': dict(Counter(k.kind for k in owners)),
            'roles': dict(Counter(p.role for ps in owners.values() for p in ps)),
            'languages': dict(Counter(p.language for ps in owners.values() for p in ps)),
            'symbol_count': conn.execute('SELECT COUNT(*) FROM ci_symbols').fetchone()[0],
            'passages': len(descriptions),
            'empty_signature_passages': sum(not f['signature'].strip() for f in descriptions),
            'empty_documentation_passages': sum(not f['documentation'].strip() for f in descriptions)}
        candidates, expanded = retrieve_contextual(conn, root, request, resources.profile,
            runtime=project.context, expand_query=resources.owner_ranker.prepare_query,
            encoders={'identity': resources.words, 'behavior': resources.words})
        trace = RankingTrace(request_id=public['id'])
        matches = resources.owner_ranker.rank(request, candidates, owner_descriptions(conn, candidates),
            expanded_query=expanded, evidence_version=3, trace=trace)
        cards = build_piece_cards(matches, 'file', expanded, project.pieces.catalog)
        result = {'id': public['id'], 'repo_id': public['repo_id'], 'source_summary': summary,
            'inferred_purpose': interpret(request).purpose,
            'proposals': [{'path': c.entity.path, 'entity': c.entity.to_dict(),
                'signals': {k: float(v) for k, v in c.signals.items()}} for c in candidates],
            'numeric_order': [{'path': m.entity.path, 'score': m.score} for m in matches],
            'native_piece_paths': [card['unit']['path'] for card in cards[:10]],
            'numeric_trace': trace.to_dict(), 'cards': cards[:10]}
        try:
            detailed = project.pieces.search(replace(request, explain=True), matches,
                expanded_query=expanded, profile_version=resources.profile.fingerprint).to_dict()
            assert [r['path'] for r in detailed['results']] == [r['path'] for r in original['results']], 'Replay order drift'
            result['diagnostic_response'] = detailed
        except Exception as error:
            message = f'{type(error).__name__}: {error}'
            assert message == original.get('error'), message
            result['diagnostic_error'] = message
    p = dest / (public['id'] + '.json')
    p.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    pins[p.name] = sha(p)
    print(json.dumps({'closed': public['id'], 'candidate_pool': len(candidates),
        'inferred_purpose': result['inferred_purpose'], 'symbols': summary['symbol_count'],
        'reproduced_original_order_or_error': True}), flush=True)
assert list(resources.neural.providers) == list(resources.context.providers) == ['CPUExecutionProvider']
assert resources.neural._max_tokens == 1024
assert not any(name in sys.modules for name in ['torch', 'transformers', 'sentence_transformers'])
(dest / 'closure.json').write_text(json.dumps({'queries': 18, 'pins': pins,
    'script_sha256': sha(Path(__file__)), 'source_manifest_sha256': registration['engine_manifest_sha256'],
    'no_gold_in_diagnostic_worker': True, 'all_original_orders_or_errors_reproduced': True,
    'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'reserve': 'CLOSED'}, indent=2) + '\n')
