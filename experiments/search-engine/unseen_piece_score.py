"""Independent fixed-identity scoring after both prelocked runs close completely."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np
import verifiable_grading
from verifiable_grading import identity_hit, wilson, cluster_difference


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def unique(data):
    result = {r['id']: r for r in data}
    if len(result) != len(data):
        raise ValueError('duplicate query IDs')
    return result


def aggregate(outcomes):
    n = len(outcomes)
    return {'queries': n, **{name: {'count': sum(r[key] for r in outcomes),
        'rate': sum(r[key] for r in outcomes) / n if n else None,
        'wilson_query_level95': wilson(sum(r[key] for r in outcomes), n)}
        for name, key in (('top1', 'identity'), ('recall10', 'recall10'))}}


def validate_returned_units(answer):
    """Public answer-shape invariants require no reference access."""
    card, units = answer['card'], answer['units']
    if len(units) > 10 or len({json.dumps(u, sort_keys=True, allow_nan=False) for u in units}) != len(units):
        raise ValueError('top10 contains too many or duplicate pieces')
    if card is not None and (not units or card['unit'] != units[0]):
        raise ValueError('top1 answer disagrees with its returned order')


def evaluate_identity(cases, answers, references):
    case_map, answer_map, gold = map(unique, (cases, answers, references))
    if not case_map or set(case_map) != set(answer_map) or set(case_map) != set(gold):
        raise ValueError('complete identical query/reference/answer sets required')
    outcomes = []
    for qid, case in case_map.items():
        answer = answer_map[qid]; card = answer['card']; units = answer['units']
        accepted = gold[qid]['acceptable_units']
        if not accepted or any(u['target_kind'] != case['target_kind'] for u in accepted):
            raise ValueError('reference kind disagrees with the requested piece')
        validate_returned_units(answer)
        outcomes.append({'id': qid, 'repo_id': case['repo_id'], 'target_kind': case['target_kind'],
            'language': case.get('language', 'unspecified'),
            'query_style': case.get('query_style', 'unspecified'),
            'identity': identity_hit(card, accepted),
            'recall10': any(identity_hit({'unit': u}, accepted) for u in units)})
    result = aggregate(outcomes)
    result['strata'] = {}
    for field in ('target_kind', 'language', 'query_style', 'repo_id'):
        groups = defaultdict(list)
        for row in outcomes:
            groups[row[field]].append(row)
        result['strata'][field] = {key: aggregate(values) for key, values in sorted(groups.items())}
    rates = [r['top1']['rate'] for r in result['strata']['repo_id'].values()]
    result['macro_repo_top1'] = float(np.mean(rates))
    result['observed_floors'] = {'top1_at_least90_percent': result['top1']['rate'] >= .90,
                                  'recall10_at_least98_5_percent': result['recall10']['rate'] >= .985}
    return result, outcomes


def load_closed(path):
    path = Path(path)
    registration = json.loads((path / 'registration.json').read_text())
    if registration['status'] != 'ALL additional public outputs closed without Gold':
        raise ValueError('both complete runs must be closed before reference access')
    answers = []; times = []; memory = []
    for repo, pins in registration['closed'].items():
        for name, expected in pins.items():
            if sha(path / repo / name) != expected:
                raise ValueError('closed output changed')
        answers.extend(rows(path / repo / 'answers.jsonl'))
        perf = json.loads((path / repo / 'performance.json').read_text())
        if perf['providers'] != ['CPUExecutionProvider'] or perf['heavy_imports']:
            raise ValueError('CPU execution policy failed')
        times.extend(perf['timings'])
        memory.append(perf['peak_rss_native'] * (1 if perf['rss_unit'] == 'bytes' else 1024))
    if not answers or len(times) != len(answers):
        raise ValueError('complete answer and timing rows required')
    timing_ids = [row['id'] for row in times]
    if len(set(timing_ids)) != len(timing_ids) or set(timing_ids) != set(unique(answers)):
        raise ValueError('timing rows must match every answer ID exactly')
    runtime = {'p50_ms': float(np.median([r['ms'] for r in times])),
        'p95_ms': float(np.quantile([r['ms'] for r in times], .95)),
        'max_ms': max(r['ms'] for r in times), 'peak_rss_bytes': max(memory),
        'cpu_ms_p50': float(np.median([r['cpu_ms'] for r in times]))}
    return registration, answers, runtime


def main():
    p = argparse.ArgumentParser()
    for name in ('baseline', 'candidate', 'lock', 'output', 'private-output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--gold', type=Path, nargs=2, required=True)
    args = p.parse_args()
    baseline, base_answers, base_runtime = load_closed(args.baseline)
    candidate, new_answers, new_runtime = load_closed(args.candidate)
    if baseline['lock_sha256'] != sha(args.lock) or candidate['lock_sha256'] != sha(args.lock):
        raise ValueError('runs do not share the prelocked evaluation')
    lock = json.loads(args.lock.read_text())
    if lock['scorer_sha256'] != sha(__file__):
        raise ValueError('scorer changed after lock')
    if lock['grading_sha256'] != sha(verifiable_grading.__file__):
        raise ValueError('grading dependency changed after lock')
    if args.baseline.resolve() == args.candidate.resolve():
        raise ValueError('baseline and candidate must be distinct captures')
    for registration, role in ((baseline, 'baseline'), (candidate, 'optimized')):
        if (registration['variant'] != role
                or registration['variant_policy'] != lock['variants'][role]):
            raise ValueError('capture variant differs from its predeclared role/policy')
    cases = rows(lock['public_cases'])
    if len(cases) != lock['queries']:
        raise ValueError('query count differs from lock')
    for path, expected in lock['input_pins'].items():
        if sha(path) != expected:
            raise ValueError('prelocked public input changed')
    base_map, new_map = unique(base_answers), unique(new_answers)
    case_map = unique(cases)
    if not case_map or set(base_map) != set(case_map) or set(new_map) != set(case_map):
        raise ValueError('both captures must contain the full public query set before Gold access')
    for qid in base_map:
        for answer in (base_map[qid], new_map[qid]):
            validate_returned_units(answer)
            if any(answer[key] != case_map[qid][key] for key in ('repo_id', 'target_kind')):
                raise ValueError('answer request metadata differs from the public query')
        if base_map[qid]['native_units'] != new_map[qid]['native_units']:
            raise ValueError('runtime optimization changed initial top10 membership/order')
        if base_map[qid]['pool_sha256'] != new_map[qid]['pool_sha256']:
            raise ValueError('runtime optimization changed source cards/pool')
    # References are first opened only after both closures and all public guards.
    references = []
    for path in args.gold:
        expected = lock['reference_pins'][str(path.resolve())]
        if sha(path) != expected:
            raise ValueError('independently sealed references changed')
        references.extend(rows(path))
    base_summary, base_rows = evaluate_identity(cases, base_answers, references)
    new_summary, new_rows = evaluate_identity(cases, new_answers, references)
    report = {'scope': 'Additional independently curated query holdout, same eight repositories; not new-repository generalization',
        'baseline': base_summary, 'candidate': new_summary,
        'paired': cluster_difference(new_rows, base_rows, key='identity'),
        'cpu': {'baseline': base_runtime, 'candidate': new_runtime},
        'lock_sha256': sha(args.lock), 'scorer_sha256': sha(__file__),
        'limits': 'Report separately from tuned development200. Query-level Wilson intervals ignore within-repository dependence; no population90% guarantee. v104 intersection not verified; v104 unopened.'}
    args.output.mkdir(parents=True, exist_ok=False)
    args.private_output.mkdir(parents=True, exist_ok=False)
    (args.private_output / 'graded-rows.json').write_text(json.dumps({'baseline': base_rows, 'candidate': new_rows}, indent=2))
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2))
    (args.output / 'registration.json').write_text(json.dumps({'scorer_sha256': sha(__file__),
        'baseline_registration_sha256': sha(args.baseline / 'registration.json'),
        'candidate_registration_sha256': sha(args.candidate / 'registration.json'),
        'summary_sha256': sha(args.output / 'summary.json')}, indent=2))
    print(json.dumps({'queries': len(cases), 'baseline': base_summary['top1'], 'candidate': new_summary['top1']}))


if __name__ == '__main__':
    main()
