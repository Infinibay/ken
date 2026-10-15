"""Replay two prospectively fixed rejection/order policies, without principal Gold."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ettin_cpu import sha
from verifiable_filter import conservative_threshold


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def select_order(scores, threshold, policy):
    if policy not in {'neural', 'preserve_ken'}:
        raise ValueError('unknown ordering policy')
    if not math.isfinite(threshold) or any(not math.isfinite(s) for s in scores):
        raise ValueError('nonfinite score/cutoff')
    survivors = [i for i, score in enumerate(scores) if score >= threshold]
    return sorted(survivors, key=lambda i: (-scores[i], i)) if policy == 'neural' else survivors


def main():
    parser = argparse.ArgumentParser()
    for name in ('comparison', 'principal-judgment-seal', 'calibration-scores', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--calibration-gold', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    comparison = json.loads((args.comparison / 'registration.json').read_text())
    seal = json.loads(args.principal_judgment_seal.read_text())
    if (comparison.get('status') != 'ALL outputs closed without Gold or quality grading'
            or seal.get('status') != 'ALL principal blind judgments closed before Gold'):
        raise ValueError('principal outputs and blind judgments must close before calibration Gold')
    for path, expected in seal['judgment_files'].items():
        if sha(path) != expected:
            raise ValueError('sealed judgment changed')
    for arm, repos in comparison['closed_workers'].items():
        for repo, files in repos.items():
            for name, expected in files.items():
                if sha(args.comparison / arm / repo / name) != expected:
                    raise ValueError('closed worker changed')
    # Only separate calibration labels are read, after the initial blind seal.
    labels = [r for path in args.calibration_gold for r in rows(path)]
    if len(labels) != 60 or len({r['card_id'] for r in labels}) != 60:
        raise ValueError('all60 distinct calibration cards required')
    protected = [r for r in labels if r['variant'] != 'faithful_plausible_distractor']
    if len(protected) != 40:
        raise ValueError('all40 correct-unit calibration cards must be protected')
    score_registration = args.calibration_scores / 'registration.json'
    score_pins = json.loads(score_registration.read_text())
    pools = {r['id']: r for p in (args.comparison / 'baseline').glob('*/pools.jsonl') for r in rows(p)}
    if len(pools) != 200:
        raise ValueError('all200 principal pools required')
    args.output.mkdir(parents=True, exist_ok=False)
    registration = {'scope': 'fixed-score offline shadows; no principal Gold or new live latency measurement',
        'policy': 'inclusive min score of40 faithful correct-unit calibration cards, including sparse evidence',
        'principal_judgment_seal_sha256': sha(args.principal_judgment_seal),
        'comparison_sha256': sha(args.comparison / 'registration.json'),
        'calibration_scores_registration_sha256': sha(score_registration),
        'calibration_gold': {str(p): sha(p) for p in args.calibration_gold},
        'script_sha256': sha(__file__), 'models': {}}
    for arm in ('17m', '32m', '68m'):
        scorefile = args.calibration_scores / (arm + '-scores.jsonl')
        if sha(scorefile) != score_pins['models'][arm]['scores_sha256']:
            raise ValueError('calibration scores changed')
        scores = {r['card_id']: r['score'] for r in rows(scorefile)}
        if set(scores) != {r['card_id'] for r in labels}:
            raise ValueError('calibration score scope differs')
        threshold = conservative_threshold(scores, labels)
        known_irrelevant = [r for r in labels if r['expected_relevance'] == 0]
        output = []
        for path in sorted((args.comparison / arm).glob('*/pools.jsonl')):
            for row in rows(path):
                pool = pools[row['id']]
                if pool['pool_sha256'] != row['pool_sha256']:
                    raise ValueError('principal pool mismatch')
                model_scores = row['scores']
                bypass = bool(pool['exact'] and pool['cards'])
                if model_scores is None and not (bypass or not pool['cards']):
                    raise ValueError('missing model scores')
                if model_scores is not None and len(model_scores) != min(10, len(pool['cards'])):
                    raise ValueError('only fixed first10 may be scored')
                for policy in ('neural', 'preserve_ken'):
                    kept = list(row['order']) if bypass else select_order(model_scores or [], threshold, policy)
                    if policy == 'neural' and kept and kept[0] != row['order'][0]:
                        raise ValueError('same-score filtering cannot improve neural top1')
                    output.append({'id': row['id'], 'arm': arm, 'policy': policy, 'kept': kept,
                        'top_index': kept[0] if kept else None, 'all_rejected': not kept, 'exact_bypass': bypass})
        if len(output) != 400 or len({(r['id'], r['policy']) for r in output}) != 400:
            raise ValueError('all200 cases required in both shadow policies')
        out = args.output / (arm + '-selections.jsonl')
        out.write_text(''.join(json.dumps(r) + '\n' for r in output))
        registration['models'][arm] = {'threshold': threshold,
            'protected_kept': sum(scores[r['card_id']] >= threshold for r in protected), 'protected': 40,
            'known_irrelevant': len(known_irrelevant),
            'known_irrelevant_discarded': sum(scores[r['card_id']] < threshold for r in known_irrelevant),
            'selections_sha256': sha(out)}
    (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))


if __name__ == '__main__':
    main()
