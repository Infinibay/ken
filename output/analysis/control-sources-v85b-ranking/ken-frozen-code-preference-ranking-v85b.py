"""Fit only reviewed repository-excluded ridge heads on frozen joint evidence."""
import gc
import sqlite3
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import ken
import numpy as np

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from pair_preferences import LinearPreference, preference_moments, ridge_preference, training_indices
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.presentation import present

SOURCE = ROOT/'output/analysis/frozen-code-preference-features-v85b'
OUT = ROOT/'output/analysis/frozen-code-preference-ranking-v85b'
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
BASE = ROOT/'output/analysis/source7-context-views-ranking-v69'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
assert receipt == '4f44d3303cae3033f11672848ed022e95b70bb7877c956d10f9c23487897c335'
while True:
    try:
        prepared = json.loads((SOURCE/'registration.json').read_text())
        if prepared.get('complete') is True:
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
assert prepared['engine_receipt'] == receipt and prepared['phases']['evaluation']['queries'] == prepared['phases']['training']['queries'] == 400
assert sha(ROOT/'output/analysis/control-sources-v85b-source/ken-frozen-code-preference-features-v85b.py') == prepared['script_sha256']
assert all(sha(path) == digest for path, digest in prepared['inputs'].items())
assert all(sha(path) == digest for path, digest in prepared['source_bindings'].items())
assert sha(ENGINE/'experiments/search-engine/cpu-frozen-code-preference-v85b.md') == prepared['protocol_sha256']
assert sha(SOURCE/'evaluation-seal.json') == prepared['evaluation_seal_sha256']
sealed = json.loads((SOURCE/'evaluation-seal.json').read_text())
assert sealed == {'pair_policy_id': prepared['pair_policy_id'], 'evaluation_queries': prepared['evaluation_queries'], 'evaluation': prepared['phases']['evaluation']}
assert sha(PARENT/'registration.json') == '74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
bindings = validate_replay_parent(PARENT, POOL)
assert len(bindings) == 51 and bindings == prepared['parent_bindings']
assert sha(BASE/'registration.json') == '9bb0d87b2f5306c7b3eee1a6484e271c6b3cfdb182fc3d408663bef6344fe814'
assert sha(DATA) == '06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
base_path = BASE/'contract_body251/scores.npy'
assert sha(base_path) == 'c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3'
with np.load(DATA) as data:
    original = {key: data[key] for key in ('qid', 'repo', 'y')}
base_scores = np.load(base_path)
requests = {}
for path in sorted((POOL/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
with (POOL/'candidates.jsonl').open() as stream:
    query_texts = {row['id']: row['expanded_query'] for row in map(json.loads, stream)}
assert set(query_texts) == set(requests)
roots = {name: Path(path) for name, path in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(requests) == 400 and set(requests) == set(original['qid']) == set(prepared['evaluation_queries']) == set(prepared['training_queries'])
case_rows = {qid: np.flatnonzero(original['qid'] == qid) for qid in requests}
arrays, pair_bindings = {}, {}
for phase in ('evaluation', 'training'):
    path = SOURCE/(phase+'-pairs.npz')
    assert sha(path) == prepared['phases'][phase]['pairs_sha256']
    pair_bindings[str(path)] = sha(path)
    with np.load(path) as data:
        arrays[phase] = {key: data[key] for key in data.files}
    joint = arrays[phase]['joint']
    assert joint.shape == (prepared['phases'][phase]['rows'], 768) and joint.dtype == np.float32 and np.isfinite(joint).all()
    assert all(len(value) == len(joint) for value in arrays[phase].values())
pair_rows = {phase: {qid: np.flatnonzero(values['qid'] == qid) for qid in requests} for phase, values in arrays.items()}
moments = {repo: {'gram': np.zeros((768, 768)), 'linear': np.zeros(768), 'queries': 0, 'query_ids': []} for repo in roots}
training_choices = {}
for current_repo in sorted(roots):
    pools = load_pools(POOL, requests, repositories=[current_repo])
    assert set(pools) == {qid for qid, row in requests.items() if row['repo_id'] == current_repo}
    db = sqlite3.connect(f'file:{ROOT/"output/analysis/context-views-source7-v69"/(current_repo+"-source.db")}?mode=ro', uri=True)
    documents = {EntityKey(**json.loads(entity)): (digest, text_hash, text)
        for entity, digest, text_hash, text in db.execute("SELECT entity,source_hash,o.text_hash,text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE view='implementation'")}
    for qid, request in requests.items():
        if request['repo_id'] != current_repo:
            continue
        repo, pool, original_rows = request['repo_id'], pools[qid], case_rows[qid]
        assert len(pool) == len(original_rows) and all(original['repo'][original_rows] == repo)
        exact = bool(len(pool) == 1 and pool[0].signals.get('exact'))
        base_order = sorted(range(len(pool)), key=lambda index: (-pool[index].signals.get('exact', 0), -base_scores[original_rows[index]], index))
        assert prepared['evaluation_queries'][qid] == {'repo': repo, 'indices': base_order[:20], 'exact': exact}
        positive, negative = training_indices(original['y'][original_rows],
            [candidate.signals.get('rrf', 0.) for candidate in pool], max_negatives=20)
        reason = 'exact_bypass' if exact else 'no_positive' if not len(positive) else 'no_negative' if not len(negative) else None
        chosen = [] if reason else [int(index) for index in np.concatenate((positive, negative))]
        expected = {'repo': repo, 'positive_indices': positive.tolist(), 'negative_indices': negative.tolist(),
            'indices': chosen, 'skip_reason': reason, 'priority': 'original-untrained-retrieval-rrf;not69scores'}
        assert prepared['training_queries'][qid] == expected
        training_choices[qid] = expected
        for phase, selected in (('evaluation', base_order[:20]), ('training', chosen)):
            rows, values = pair_rows[phase][qid], arrays[phase]
            assert np.array_equal(values['index'][rows], selected)
            assert set(values['repo'][rows]) <= {repo}
            for row, index in zip(rows, selected, strict=True):
                assert EntityKey(**json.loads(str(values['entity'][row]))) == pool[index].entity
                assert str(values['source_hash'][row]) == pool[index].passages[0].source_hash
                assert bool(values['exact'][row]) == exact
                assert str(values['query_hash'][row]) == hashlib.sha256(query_texts[qid].encode()).hexdigest()
                if exact:
                    assert not values['joint'][row].any() and str(values['document_hash'][row]) == ''
                else:
                    assert np.isclose(np.linalg.norm(values['joint'][row].astype(np.float64)), 1., rtol=0., atol=1e-6)
                    digest, document_hash, text = documents[pool[index].entity]
                    assert digest == pool[index].passages[0].source_hash
                    assert hashlib.sha256(text.encode()).hexdigest() == document_hash == str(values['document_hash'][row])
        evaluation = {int(arrays['evaluation']['index'][row]): row for row in pair_rows['evaluation'][qid]}
        for row in pair_rows['training'][qid]:
            index = int(arrays['training']['index'][row])
            if index in evaluation:
                other = evaluation[index]
                assert np.array_equal(arrays['training']['joint'][row], arrays['evaluation']['joint'][other])
                for name in ('query_hash', 'document_hash', 'source_hash', 'entity'):
                    assert arrays['training'][name][row] == arrays['evaluation'][name][other]
        if reason is None:
            values = arrays['training']['joint'][pair_rows['training'][qid]]
            gram, linear = preference_moments(values[:len(positive)], values[len(positive):])
            moments[repo]['gram'] += gram
            moments[repo]['linear'] += linear
            moments[repo]['queries'] += 1
            moments[repo]['query_ids'].append(qid)
    db.close()
    del pools, pool, documents
    gc.collect()
manifest = {'scope': 'frozenCodeRank85 joint projection,16whole-repo-excluded ridge1heads,source69prefix20 evaluation only; no default/private/90% claim',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'source_registration_sha256': sha(SOURCE/'registration.json'),
    'protocol_sha256': prepared['protocol_sha256'], 'pair_policy_id': prepared['pair_policy_id'],
    'pair_bindings': pair_bindings, 'parent_bindings': bindings,
    'parameters': {'regularization': 1., 'max_training_negatives': 20, 'training_priority': 'original-untrained-RRF',
        'evaluation_prefix': 20, 'readouts': ['raw', 'equal_rrf60'], 'intercept': False},
    'training_choices': training_choices, 'moments': {}, 'folds': [], 'results': {}, 'pre_fit_ready': True}
for repo, statistics in sorted(moments.items()):
    path = OUT/(repo+'-moments.npz')
    np.savez_compressed(path, gram=statistics['gram'], linear=statistics['linear'])
    manifest['moments'][repo] = {'sha256': sha(path), 'queries': statistics['queries'], 'query_ids': statistics['query_ids']}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'pre_fit_ready': True, 'training_queries': sum(item['queries'] for item in moments.values()),
    'waiting_for': str(OUT/'PRE-FIT-REVIEW-ACCEPTED.json')}), flush=True)
while True:
    try:
        accepted = json.loads((OUT/'PRE-FIT-REVIEW-ACCEPTED.json').read_text())
        if (accepted['engine_receipt'] == receipt and accepted['source_registration_sha256'] == manifest['source_registration_sha256']
                and accepted['fitter_script_sha256'] == manifest['script_sha256']):
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
assert sha(SOURCE/'registration.json') == manifest['source_registration_sha256']
assert all(sha(path) == digest for path, digest in pair_bindings.items())
assert bindings == validate_replay_parent(PARENT, POOL)


def training_system(held, statistics):
    gram, linear, count = np.zeros((768, 768)), np.zeros(768), 0
    for repo in sorted(name for name in roots if name != held):
        gram += statistics[repo]['gram']
        linear += statistics[repo]['linear']
        count += statistics[repo]['queries']
    return gram, linear, count


heads = {}
for held in sorted(roots):
    gram, linear, count = training_system(held, moments)
    perturbed = {**moments, held: {'gram': np.full((768, 768), np.nan),
        'linear': np.full(768, np.nan), 'queries': -1000000}}
    other_gram, other_linear, other_count = training_system(held, perturbed)
    assert np.array_equal(gram, other_gram) and np.array_equal(linear, other_linear) and count == other_count
    training_qids = [qid for repo in sorted(roots) if repo != held for qid in moments[repo]['query_ids']]
    assert len(training_qids) == len(set(training_qids)) == count
    assert all(requests[qid]['repo_id'] != held for qid in training_qids)
    head = ridge_preference(gram, linear, regularization=1.)
    assert float(head.weights@head.weights) <= count+1e-7
    record = {'schema': 'frozen-code-preference-v1', 'pair_policy_id': prepared['pair_policy_id'],
        'weights': head.weights.tolist(), 'regularization': 1., 'intercept': False,
        'held_out': held, 'training_repos': sorted(set(roots)-{held}), 'training_query_ids': training_qids}
    path = OUT/(held+'-head.json')
    path.write_text(json.dumps(record, separators=(',', ':')))
    restored = LinearPreference(np.array(json.loads(path.read_text())['weights']))
    assert np.array_equal(restored.weights, head.weights)
    selected = np.flatnonzero((arrays['evaluation']['repo'] == held) & ~arrays['evaluation']['exact'])
    assert np.array_equal(head.score(arrays['evaluation']['joint'][selected]), restored.score(arrays['evaluation']['joint'][selected]))
    heads[held] = restored
    manifest['folds'].append({'held_out': held, 'training_repos': sorted(set(roots)-{held}),
        'training_queries': count, 'head_sha256': sha(path), 'weights_squared_norm': float(head.weights@head.weights),
        'held_nan_moments_ignored': True})
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'head_fitted': held, 'training_queries': count}), flush=True)
responses = {name: [] for name in ('baseline', 'raw', 'equal_rrf60')}
scored = []
producer = json.loads((BASE/'registration.json').read_text())
for repo in sorted(roots):
    pools = load_pools(POOL, requests, repositories=[repo])
    assert set(pools) == {qid for qid, row in requests.items() if row['repo_id'] == repo}
    native = NumericRanker.from_dict(json.loads((BASE/'contract_body251'/(repo+'-numeric.json')).read_text()))
    fold = next(item for item in producer['modes']['contract_body251']['folds'] if item['held_out'] == repo)
    assert native.fingerprint == fold['model_fingerprint'] and set(fold['training_repos']) == set(roots)-{repo}
    for qid in sorted(qid for qid, row in requests.items() if row['repo_id'] == repo):
        pool, original_rows = pools[qid], case_rows[qid]
        base_order = sorted(range(len(pool)), key=lambda index: (-pool[index].signals.get('exact', 0), -base_scores[original_rows[index]], index))
        prefix = base_order[:20]
        exact = prepared['evaluation_queries'][qid]['exact']
        vectors = arrays['evaluation']['joint'][pair_rows['evaluation'][qid]]
        logits = np.zeros(len(prefix)) if exact else heads[repo].score(vectors)
        pair_order = sorted(range(len(prefix)), key=lambda index: (-logits[index], index))
        ranks = {index: rank for rank, index in enumerate(pair_order, 1)}
        fused = np.array([1./(60+index+1)+1./(60+ranks[index]) for index in range(len(prefix))])
        scored.append({'id': qid, 'indices': prefix, 'logits': logits.tolist(), 'exact_bypass': exact})
        for mode, values in (('baseline', None), ('raw', logits), ('equal_rrf60', fused)):
            if values is None:
                order, visible, profile = base_order, {}, native.fingerprint
            else:
                positions = sorted(range(len(prefix)), key=lambda index: (-pool[prefix[index]].signals.get('exact', 0), -values[index], index))
                order = [prefix[index] for index in positions]+base_order[20:]
                assert order[20:] == base_order[20:] and set(order[:len(prefix)]) == set(prefix)
                visible = {index: float(value) for index, value in zip(prefix, values, strict=True)}
                profile = hashlib.sha256(json.dumps({'head': sha(OUT/(repo+'-head.json')), 'mode': mode,
                    'source_ranker': native.fingerprint, 'pair_policy': prepared['pair_policy_id'],
                    'presentation': 'source69prefix20-exact-authority-tail-evidence3'}, sort_keys=True).encode()).hexdigest()
            assert len(order) == len(set(order)) == len(pool)
            matches = [CodeMatch(pool[index].entity, visible.get(index, float(base_scores[original_rows[index]])),
                pool[index].passages, pool[index].passages[0].source_hash, pool[index].signals, pool[index].owned_regions) for index in order]
            request = SearchRequest(**requests[qid]['request'])
            matches = complete_evidence(matches, roots[repo], request)
            responses[mode].append({'id': qid, **present(matches, roots[repo], request, profile_version=profile).to_dict()})
    del pools, pool, matches
    gc.collect()
(OUT/'scored-prefixes.json').write_text(json.dumps(scored, indent=2))
assert sha(SOURCE/'registration.json') == manifest['source_registration_sha256']
assert all(sha(path) == digest for path, digest in pair_bindings.items())
assert all(sha(path) == digest for path, digest in prepared['inputs'].items())
assert all(sha(path) == digest for path, digest in prepared['source_bindings'].items())
for repo, metadata in prepared['indexed_source_repos'].items():
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['file_hashes'].items())
assert bindings == validate_replay_parent(PARENT, POOL)
assert verify_frozen_source(ENGINE) == receipt
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
from ken.bench.retrieval import evaluate
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
for mode, values in responses.items():
    assert len(values) == len({row['id'] for row in values}) == 400
    report = evaluate(cases, values, roots=roots)
    if mode == 'baseline':
        assert report['strict_top1'] == {'hits': 286, 'total': 400, 'rate': .715}
        assert report['identity_top1'] == {'hits': 298, 'total': 400, 'rate': .745}
    (OUT/(mode+'-responses.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in values))
    (OUT/(mode+'-report.json')).write_text(json.dumps(report, indent=2))
    manifest['results'][mode] = {'strict': report['strict_top1'], 'identity': report['identity_top1'], 'missing': report['missing_response_ids']}
    print(json.dumps({'mode': mode, **manifest['results'][mode]}), flush=True)
manifest['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
manifest['heavy_runtimes_imported'] = []
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
