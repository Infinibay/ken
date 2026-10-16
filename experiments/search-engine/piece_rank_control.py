"""Fixed-policy repository-excluded development CV for requested-piece ranking."""
import argparse
import itertools
import json
from pathlib import Path
import time

import ken
import numpy as np
from lightgbm import LGBMRanker
from ken.bench.numeric_export import export_numeric_ranker
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.piece_ranking import PIECE_FEATURES
from ken.retrieval.intent import requested_piece_path
from ken.retrieval.model import SearchRequest
from verifiable_grading import identity_hit, cluster_difference
from ettin_cpu import sha

KNOWN = {
    '/private/tmp/ken-verifiable-pieces-benchmark-20261015/main-cs/gold/cases.jsonl':
        'c75358d696f976d2444421dc98e9bf3bc0070dc662cedbbe288cd0a52509ed12',
    '/private/tmp/ken-verifiable-pieces-module-file-20261015/gold/cases.jsonl':
        '7297632bd221252485c79ad8a8badb450de512179366e72983247a8a8b7533ed'}
PARAMETERS = dict(n_estimators=160, num_leaves=15, min_child_samples=40, reg_lambda=2,
                  learning_rate=.08, lambdarank_truncation_level=5, n_jobs=1, random_state=42)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser()
    for name in ('features', 'public-cases', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    engine = Path(ken.__file__).resolve().parents[2]
    receipt = verify_frozen_source(engine)
    captured = json.loads((args.features / 'registration.json').read_text())
    assert captured['status'] == 'ALL200 typed piece features closed without Gold'
    assert captured['features'] == list(PIECE_FEATURES)
    assert sha(args.public_cases) == captured['public_cases_sha256']
    arrays = []; candidates = []
    for repo, pins in captured['closed'].items():
        assert all(sha(args.features / repo / name) == digest for name, digest in pins.items())
        data = np.load(args.features / repo / 'features.npz', allow_pickle=False)
        batch = rows(args.features / repo / 'candidates.jsonl')
        assert [r['id'] for r in batch] == data['qid'].tolist()
        assert all(r['repo_id'] == repo for r in batch)
        arrays.append(data['x']); candidates.extend(batch)
    X = np.concatenate(arrays)
    assert X.shape == (len(candidates), len(PIECE_FEATURES)) and np.isfinite(X).all()
    qids = np.array([r['id'] for r in candidates]); repos = np.array([r['repo_id'] for r in candidates])
    groups = {qid: np.flatnonzero(qids == qid) for qid in dict.fromkeys(qids)}
    cases = {r['id']: r for r in rows(args.public_cases)}
    assert set(groups) == set(cases) and len(cases) == 200
    args.output.mkdir(parents=True, exist_ok=False)
    registration = {'scope': 'ALL200 exposed-development leave-one-repository-out CV; requested-piece model, same native top10 membership; not private acceptance',
        'parameters': PARAMETERS, 'features': list(PIECE_FEATURES), 'source_receipt': receipt,
        'feature_capture_sha256': sha(args.features / 'registration.json'),
        'policy': 'One fixed parameter set; train only other seven repositories and positive-containing groups; score every held-out query including missing positives; apply piece ordering to class/module/file only, preserving symbol order; no per-case fallback or post-score parameter search.',
        'status': 'registered before fixed-reference labels and fitting', 'folds': []}
    (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
    gold = {}
    for path, expected in KNOWN.items():
        assert sha(path) == expected
        gold.update({r['id']: r for r in rows(path)})
    assert set(gold) == set(cases)
    y = np.array([identity_hit({'unit': r['unit']}, gold[r['id']]['acceptable_units']) for r in candidates], dtype=int)
    trainable = np.zeros(len(candidates), dtype=bool)
    for indices in groups.values():
        trainable[indices] = y[indices].any()
    scores = np.zeros(len(candidates), dtype=float)
    for held in sorted(set(repos)):
        train = (repos != held) & trainable; test = repos == held
        assert held not in set(repos[train])
        sizes = [len(list(g)) for _, g in itertools.groupby(qids[train])]
        started = time.perf_counter()
        fitted = LGBMRanker(objective='lambdarank', verbosity=-1, **PARAMETERS)
        fitted.fit(X[train], y[train], group=sizes, feature_name=list(PIECE_FEATURES))
        numeric = export_numeric_ranker(fitted.booster_.dump_model(), features=PIECE_FEATURES)
        pred = numeric.predict(X[test])
        assert np.array_equal(pred, fitted.booster_.predict(X[test]))
        scores[test] = pred
        model = args.output / (held + '-numeric.json')
        model.write_text(json.dumps(numeric.to_dict(), separators=(',', ':')))
        registration['folds'].append({'held_out': held, 'training_repos': sorted(set(repos[train])),
            'training_queries': len(set(qids[train])), 'test_queries': len(set(qids[test])),
            'model_sha256': sha(model), 'model_fingerprint': numeric.fingerprint,
            'fit_ms': (time.perf_counter() - started) * 1000})
        print(json.dumps({'fold_closed': held}), flush=True)
    np.save(args.output / 'scores.npy', scores)
    baseline = []; proposed = []; answers = []
    for qid, indices in groups.items():
        named_path = requested_piece_path(SearchRequest(cases[qid]['query']))
        order = sorted(indices, key=lambda i: (
            -float(named_path is not None and candidates[i]['unit']['path']==named_path),
            -candidates[i]['exact'], -scores[i], candidates[i]['native_rank']))
        if cases[qid]['target_kind'] == 'symbol':
            order = list(indices)
        assert set(order) == set(indices)
        for arm, selected in ((baseline, indices), (proposed, order)):
            arm.append({'id': qid, 'repo_id': cases[qid]['repo_id'], 'target_kind': cases[qid]['target_kind'],
                'identity': bool(y[selected[0]]), 'recall10': bool(y[selected].any())})
        answers.append({'id': qid, 'units': [candidates[i]['unit'] for i in order],
                        'scores': [float(scores[i]) for i in order]})
    assert len(answers) == 200 and verify_frozen_source(engine) == receipt
    (args.output / 'answers.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in answers))
    registration['status'] = 'ALL200 repository-excluded orders closed'
    registration['answers_sha256'] = sha(args.output / 'answers.jsonl')
    (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
    base = {r['id']: r for r in baseline}
    summary = {'scope': registration['scope'], 'queries': 200,
        'baseline': {k: sum(r[k] for r in baseline) for k in ('identity', 'recall10')},
        'proposed': {k: sum(r[k] for r in proposed) for k in ('identity', 'recall10')},
        'by_kind': {kind: {name: sum(r['identity'] for r in arm if r['target_kind'] == kind)
            for name, arm in (('baseline', baseline), ('proposed', proposed))}
            for kind in ('class', 'module', 'symbol', 'file')},
        'gains': [r['id'] for r in proposed if r['identity'] and not base[r['id']]['identity']],
        'losses': [r['id'] for r in proposed if not r['identity'] and base[r['id']]['identity']],
        'paired': cluster_difference(proposed, baseline, key='identity'),
        'registration_sha256': sha(args.output / 'registration.json')}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    (args.output / 'graded-rows.json').write_text(json.dumps({'baseline': baseline, 'proposed': proposed}, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
