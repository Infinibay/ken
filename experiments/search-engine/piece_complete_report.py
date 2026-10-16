"""Grade a completely closed fresh CPU run against exposed development labels."""
import argparse
import json
from pathlib import Path

import numpy as np
from ettin_cpu import sha
from verifiable_grading import identity_hit, cluster_difference


KNOWN = {
    '/private/tmp/ken-verifiable-pieces-benchmark-20261015/main-cs/gold/cases.jsonl':
        'c75358d696f976d2444421dc98e9bf3bc0070dc662cedbbe288cd0a52509ed12',
    '/private/tmp/ken-verifiable-pieces-module-file-20261015/gold/cases.jsonl':
        '7297632bd221252485c79ad8a8badb450de512179366e72983247a8a8b7533ed'}


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registration = json.loads((args.capture / 'registration.json').read_text())
    if registration['status'] != 'ALL200 complete CPU outputs closed without Gold':
        raise ValueError('ALL200 must be closed before reference access')
    for path, digest in registration['input_pins'].items():
        if sha(path) != digest:
            raise ValueError('registered input changed')
    answers = []; orders = {}; timings = []; resources = {}
    for repo, files in registration['closed'].items():
        for name, digest in files.items():
            if sha(args.capture / repo / name) != digest:
                raise ValueError('closed worker output changed')
        answers.extend(rows(args.capture / repo / 'answers.jsonl'))
        orders.update({r['id']: r for r in rows(args.capture / repo / 'orders.jsonl')})
        performance = json.loads((args.capture / repo / 'performance.json').read_text())
        if performance['providers'] != ['CPUExecutionProvider'] or performance['heavy_imports']:
            raise ValueError('CPU/no-heavy-import requirement failed')
        times = performance['timings']
        timings.extend(times)
        unit = 1 if performance['rss_unit'] == 'bytes' else 1024
        resources[repo] = {'files': performance['indexed_files'], 'queries': len(times),
            'p50_ms': float(np.median([r['ms'] for r in times])),
            'p95_ms': float(np.quantile([r['ms'] for r in times], .95)),
            'max_ms': max(r['ms'] for r in times),
            'peak_rss_bytes': performance['peak_rss_native'] * unit,
            'asset_load_ms': performance['asset_load_ms'], 'warmup_ms': performance['warmup_ms']}
        resources[repo]['p95_ms_per_100_files'] = resources[repo]['p95_ms'] * 100 / performance['indexed_files']
    if len(answers) != 200 or len({r['id'] for r in answers}) != 200 or len(timings) != 200:
        raise ValueError('exactly ALL200 required')
    for answer in answers:
        order = orders[answer['id']]
        if sorted(order['final_order']) != list(range(len(order['native_units']))):
            raise ValueError('native top10 membership differs')
        if answer['units'] != [order['native_units'][i] for i in order['final_order']]:
            raise ValueError('actual answer and final order differ')
        if answer['card']['unit'] != answer['units'][0]:
            raise ValueError('returned answer differs from top1')
    # No reference bytes are opened before all output hashes and counts pass.
    gold = {}
    for path, digest in KNOWN.items():
        if sha(path) != digest:
            raise ValueError('fixed exposed references changed')
        gold.update({r['id']: r for r in rows(path)})
    if set(gold) != {r['id'] for r in answers}:
        raise ValueError('reference query set differs')
    graded = []; baseline = []; pieces = []
    for answer in answers:
        order = orders[answer['id']]; acceptable = gold[answer['id']]['acceptable_units']
        for output, units in ((graded, answer['units']), (baseline, order['native_units']),
                              (pieces, [order['native_units'][i] for i in order['piece_order']])):
            output.append({k: answer[k] for k in ('id', 'repo_id', 'target_kind')} | {
                'identity': identity_hit({'unit': units[0]}, acceptable),
                'recall10': any(identity_hit({'unit': u}, acceptable) for u in units)})
    base = {r['id']: r for r in baseline}; prior = {r['id']: r for r in pieces}
    summary = {'scope': registration['scope'], 'queries': 200,
        'counts': {name: {key: sum(r[key] for r in values) for key in ('identity', 'recall10')}
                   for name, values in (('native', baseline), ('piece', pieces), ('complete', graded))},
        'by_kind': {kind: {name: sum(r['identity'] for r in values if r['target_kind'] == kind)
                          for name, values in (('native', baseline), ('piece', pieces), ('complete', graded))}
                    for kind in ('class', 'module', 'symbol', 'file')},
        'gains_vs_native': [r['id'] for r in graded if r['identity'] and not base[r['id']]['identity']],
        'losses_vs_native': [r['id'] for r in graded if not r['identity'] and base[r['id']]['identity']],
        'gains_vs_piece': [r['id'] for r in graded if r['identity'] and not prior[r['id']]['identity']],
        'losses_vs_piece': [r['id'] for r in graded if not r['identity'] and prior[r['id']]['identity']],
        'paired_vs_native': cluster_difference(graded, baseline, key='identity'),
        'paired_vs_piece': cluster_difference(graded, pieces, key='identity'),
        'cpu': {'p50_ms': float(np.median([r['ms'] for r in timings])),
                'p95_ms': float(np.quantile([r['ms'] for r in timings], .95)),
                'max_ms': max(r['ms'] for r in timings),
                'peak_rss_bytes': max(r['peak_rss_bytes'] for r in resources.values()),
                'providers': ['CPUExecutionProvider'], 'by_repo': resources},
        'timing_scope': registration['timing_scope'],
        'registration_sha256': sha(args.capture / 'registration.json'),
        'limits': 'Exposed development, eight repository-excluded forests, fixed complete CPU pipeline. Not private acceptance, evidence sufficiency, arbitrary repositories or public default.'}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2))
    (args.output / 'graded-rows.json').write_text(json.dumps({'native': baseline, 'piece': pieces, 'complete': graded}, indent=2))
    (args.output / 'registration.json').write_text(json.dumps({'producer_sha256': sha(__file__),
        'capture_registration_sha256': sha(args.capture / 'registration.json'), 'fixed_exposed_references': KNOWN,
        'summary_sha256': sha(args.output / 'summary.json'), 'graded_rows_sha256': sha(args.output / 'graded-rows.json')}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
