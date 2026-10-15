"""Exact unchanged73 ranks/scores, measured with already validated evidence3."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import ken
ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.retrieval import evaluate, request_for_case
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/marco-pair-evidence3-v73b'
ORIGINAL = ROOT/'output/analysis/marco-pair-ranking-v73'
SOURCE = ROOT/'output/analysis/marco-pair-features-v73-combined'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
registration = json.loads((ORIGINAL/'registration.json').read_text())
assert set(registration['results']) == {'tiny259', 'mini259', 'both267'}
assert all(len(registration['modes'][mode]['folds']) == 16 for mode in registration['results'])
assert all(sha(path) == digest for path, digest in registration['inputs'].items())
assert sha(DATA) == '06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
bindings = validate_replay_parent(PARENT, POOL, extension=SOURCE)
assert len(bindings) == 68
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
by_id = {case['id']: case for case in cases}
assert len(cases) == len(by_id) == 400
roots = {key: Path(value) for key, value in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
pools = load_pools(POOL, by_id)
with np.load(DATA) as data:
    qids, repos = data['qid'], data['repo']
rows = {qid: np.flatnonzero(qids == qid) for qid in by_id}
source_reg = json.loads((SOURCE/'registration.json').read_text())
manifest = {'scope': 'ALL400 same3 completed73models/OOFscores/pools;onlyevidence3;no fit or source/model/reference changes',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-marco-pair-evidence3-v73b.md'),
    'parent_bindings': bindings, 'inputs': {str(path): sha(path) for path in (DATA, ORIGINAL/'registration.json', SOURCE/'registration.json')},
    'models': {}, 'results': {}, 'complete_original_response_replay_count': {}}
for mode, columns in {'tiny259': [*range(251), *range(251,259)],
                      'mini259': [*range(251), *range(259,267)], 'both267': list(range(267))}.items():
    original_scores = np.load(ORIGINAL/mode/'scores.npy')
    assert original_scores.shape == qids.shape and np.isfinite(original_scores).all()
    manifest['inputs'][str(ORIGINAL/mode/'scores.npy')] = sha(ORIGINAL/mode/'scores.npy')
    fingerprints = {}
    for repo in sorted(roots):
        selected = np.flatnonzero(repos == repo)
        path = ORIGINAL/mode/f'{repo}-numeric.json'
        model = NumericRanker.from_dict(json.loads(path.read_text()))
        fold = next(f for f in registration['modes'][mode]['folds'] if f['held_out'] == repo)
        assert set(fold['training_repos']) == set(roots)-{repo}
        assert model.fingerprint == fold['model_fingerprint']
        assert model.features == tuple(source_reg['features'][i] for i in columns)
        with np.load(SOURCE/f'{repo}.npz') as source:
            assert np.array_equal(source['qid'], qids[selected])
            predicted = model.predict(np.ascontiguousarray(source['x'][:, columns]))
        assert np.array_equal(predicted, original_scores[selected])
        fingerprints[repo] = model.fingerprint
        manifest['models'][str(path)] = sha(path)
    old_responses = {row['id']: row for row in map(json.loads, (ORIGINAL/mode/'responses.jsonl').read_text().splitlines())}
    assert set(old_responses) == set(by_id)
    responses = []
    for case in cases:
        qid, repo = case['id'], case['repo_id']
        pool = pools[qid]
        indices = rows[qid]
        assert len(pool) == len(indices)
        values = original_scores[indices]
        order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0), -values[i], i))
        matches = [CodeMatch(pool[i].entity, float(values[i]), pool[i].passages,
            pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
        request = SearchRequest(**request_for_case(case))
        unchanged = {'id': qid, **present(matches, roots[repo], request, profile_version=fingerprints[repo]).to_dict()}
        assert unchanged == old_responses[qid]
        changed = complete_evidence(matches, roots[repo], request)
        response = {'id': qid, **present(changed, roots[repo], request, profile_version=fingerprints[repo]).to_dict()}
        responses.append(response)
    original_report = evaluate(cases, list(old_responses.values()), roots=roots)
    assert original_report == json.loads((ORIGINAL/mode/'report.json').read_text())
    report = evaluate(cases, responses, roots=roots)
    (OUT/f'{mode}-responses.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in responses))
    (OUT/f'{mode}-report.json').write_text(json.dumps(report, indent=2))
    manifest['complete_original_response_replay_count'][mode] = 400
    manifest['results'][mode] = {'strict': report['strict_top1'], 'identity': report['identity_top1'], 'missing': report['missing_response_ids']}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'mode': mode, **manifest['results'][mode]}), flush=True)
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert all(sha(path) == digest for path, digest in manifest['models'].items())
assert bindings == validate_replay_parent(PARENT, POOL, extension=SOURCE)
assert verify_frozen_source(ENGINE) == receipt
