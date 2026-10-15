"""Recovered source documentation, whole-repository exclusion and original strict scoring."""
import collections
import hashlib
import itertools
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
import ken
from lightgbm import LGBMRanker

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
sys.path.insert(0, str(Path(ken.__file__).resolve().parents[2] / 'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.numeric_export import export_numeric_ranker
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import CodeMatch, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.presentation import present
import ken

OUT = ROOT / 'output/analysis/marco-pair-ranking-v73'
OUT.mkdir(exist_ok=False)
SOURCE = ROOT / 'output/analysis/marco-pair-features-v73-combined'
BASE = ROOT / 'output/analysis/source7-ranking-v66c'
POOL = ROOT / 'output/analysis/c-source-reindex-v66c'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(Path(ken.__file__).resolve().parents[2])
while True:
    try:
        registration = json.loads((SOURCE / 'registration.json').read_text())
        if len(registration['query_repos']) == 16 and (BASE / 'training-matrix.npz').is_file():
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
assert len(registration['source_repos']) == 16
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
bindings = validate_replay_parent(PARENT, POOL, extension=SOURCE)
assert len(bindings) == 68
(OUT/'pre-fit-attestation.json').write_text(json.dumps(bindings,indent=2))
features = tuple(registration['features'])
cases = list(map(json.loads, (ROOT / 'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
by_id = {c['id']: c for c in cases}
assert len(cases) == len(by_id) == 400
roots = {k: Path(v) for k, v in json.loads((ROOT / 'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
pools = load_pools(POOL, by_id)
old = np.load(BASE / 'training-matrix.npz')
old_indices = {qid: np.flatnonzero(old['qid'] == qid) for qid in by_id}
matrices, qids, repos, targets = [], [], [], []
for repo in sorted(roots):
    data = np.load(SOURCE / f'{repo}.npz')
    assert sha(SOURCE / f'{repo}.npz') == registration['query_repos'][repo]['output_sha256']
    for qid, rows in itertools.groupby(range(len(data['qid'])), key=lambda i: str(data['qid'][i])):
        rows = np.array(list(rows))
        prior = old_indices[qid]
        assert len(rows) == len(prior) == len(pools[qid])
        assert np.array_equal(data['index'][rows], np.arange(len(rows)))
        assert np.array_equal(data['x'][rows, :235], old['x'][prior])
        assert by_id[qid]['repo_id'] == repo and set(old['repo'][prior]) == {repo}
        matrices.append(data['x'][rows])
        qids.extend([qid] * len(rows))
        repos.extend([repo] * len(rows))
        targets.extend(old['y'][prior])
X = np.concatenate(matrices)
qids, repos, targets = np.array(qids), np.array(repos), np.array(targets)
assert X.shape == (len(old['qid']), 267) and np.isfinite(X).all()
assert set(qids) == set(by_id)
del matrices, old
params = json.loads((ROOT / 'output/analysis/core-ranker-v18/registration.json').read_text())['parameters']
modes = {'tiny259': [*range(251), *range(251,259)], 'mini259': [*range(251), *range(259,267)], 'both267': list(range(267))}

manifest = {
    'scope': 'ALL400 original strict retrieved-response scoring; same pooled owners/labels; sixteen excluded-repository folds; fresh source7 pools/251parent values plus genuine joint-attention pair logits; paired source7baseline66c; no API/acceptance claim',
    'script_sha256': sha(__file__), 'engine_receipt': receipt, 'parameters': params,
    'inputs': {str(p): sha(p) for p in [SOURCE / 'registration.json', BASE / 'training-matrix.npz', POOL / 'candidates.jsonl', ROOT / 'experiments/search-engine/cpu-marco-pair-control-v73.md']},
    'modes': {}, 'results': {}, 'pre_fit_attestation_sha256': sha(OUT/'pre-fit-attestation.json'),
}
(OUT / 'registration.json').write_text(json.dumps(manifest, indent=2))
case_indices = {qid: np.flatnonzero(qids == qid) for qid in by_id}
for mode, cols in modes.items():
    started = time.perf_counter()
    folder = OUT / mode
    folder.mkdir()
    names = tuple(features[i] for i in cols)
    matrix = np.ascontiguousarray(X[:, cols])
    scores = np.zeros(len(matrix))
    profiles = {}
    folds = []
    for held in sorted(roots):
        train, test = repos != held, repos == held
        if mode == 'baseline235':
            source_model = BASE / f'{held}-numeric.json'
            model = NumericRanker.from_dict(json.loads(source_model.read_text()))
            assert model.features == names
        else:
            fitted = LGBMRanker(objective='lambdarank', verbosity=-1, **params)
            fitted.fit(matrix[train], targets[train], group=[len(list(g)) for _, g in itertools.groupby(qids[train])])
            model = export_numeric_ranker(fitted.booster_.dump_model(), features=names)
            assert np.array_equal(model.predict(matrix[test]), fitted.booster_.predict(matrix[test]))
        scores[test] = model.predict(matrix[test])
        profiles[held] = model.fingerprint
        (folder / f'{held}-numeric.json').write_text(json.dumps(model.to_dict(), separators=(',', ':')))
        folds.append({'held_out': held, 'training_repos': sorted(set(repos[train])), 'model_fingerprint': model.fingerprint})
        print(json.dumps({'mode': mode, 'fold': held}), flush=True)
    np.save(folder / 'scores.npy', scores)
    responses, coverage = [], []
    for case in cases:
        qid = case['id']
        pool = pools[qid]
        indices = case_indices[qid]
        pred, eligible = scores[indices], targets[indices]
        order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0), -pred[i], i))
        coverage.append({'id': qid, 'eligible_ranks': [rank for rank, i in enumerate(order, 1) if eligible[i]]})
        matches = [CodeMatch(pool[i].entity, float(pred[i]), pool[i].passages, pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
        request = SearchRequest(**request_for_case(case))
        response = present(matches, roots[case['repo_id']], request, profile_version=profiles[case['repo_id']]).to_dict()
        responses.append({'id': qid, **response})
    assert len(responses) == 400
    report = evaluate(cases, responses, roots=roots)
    (folder / 'report.json').write_text(json.dumps(report, indent=2))
    (folder / 'responses.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in responses))
    (folder / 'ranked-coverage.json').write_text(json.dumps({'rows': coverage, 'at1': sum(1 in r['eligible_ranks'] for r in coverage), 'at100': sum(any(rank <= 100 for rank in r['eligible_ranks']) for r in coverage), 'all400_denominator': True}, indent=2))
    manifest['modes'][mode] = {'features': names, 'folds': folds, 'ms': (time.perf_counter() - started) * 1000, 'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    manifest['results'][mode] = {'strict': report['strict_top1'], 'identity': report['identity_top1'], 'missing': report['missing_response_ids']}
    (OUT / 'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'completed': mode, **manifest['results'][mode]}), flush=True)
assert bindings == validate_replay_parent(PARENT, POOL, extension=SOURCE)
assert verify_frozen_source(Path(ken.__file__).resolve().parents[2]) == receipt
