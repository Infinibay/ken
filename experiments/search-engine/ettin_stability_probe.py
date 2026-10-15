"""Source-free same-weight INT8/FP32 batch/padding diagnosis, never quality grading."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from ettin_cpu import CPUReranker, registered_padding, sha


def aligned_scores(model, query, texts, order, single):
    if sorted(order) != list(range(len(texts))):
        raise ValueError('pair order must be a complete permutation')
    ordered = [texts[i] for i in order]
    if single:
        scored = [model.score(query, [text]) for text in ordered]
        values = [scores[0] for scores, _ in scored]
        details = [detail for _, detail in scored]
    else:
        values, detail = model.score(query, ordered)
        details = [detail]
    if len(values) != len(order):
        raise ValueError('pair score scope differs')
    aligned = [None] * len(values)
    for index, value in zip(order, values, strict=True):
        aligned[index] = value
    return aligned, details


def rank(scores):
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registrations', type=Path, nargs=2, required=True,
                        help='same published17M complete INT8 graph, then FP32 graph')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registrations = [json.loads(p.read_text()) for p in args.registrations]
    identity = lambda r: (r['upstream']['model_id'], r['upstream']['revision'], r['tokenizer_sha256'])
    if identity(registrations[0]) != identity(registrations[1]):
        raise ValueError('precision comparison must use the same published model and tokenizer')
    if registrations[1].get('encoder_precision') != 'fp32':
        raise ValueError('second precision control must be FP32')
    args.output.mkdir(parents=True, exist_ok=False)
    texts = ['def get(key): return cache[key]', 'def put(key, value): cache[key] = value',
        'def parse(text): return json.loads(text)', 'def read(path): return path.read_text()',
        'def sort(items): return sorted(items)', 'def validate(x): return x is not None',
        'def render(text): return "<p>" + text + "</p>"', 'def save(value): disk.write(value)',
        'def digest(data): return sha256(data)', 'DEFAULT_PORT = 8080']
    query = 'find code that stores and retrieves a value by key'
    profiles = [('batch4_dynamic', list(range(10)), False, None),
                ('permuted4_dynamic', [9, 0, 8, 1, 7, 2, 6, 3, 5, 4], False, None),
                ('batch1_dynamic', list(range(10)), True, None),
                ('batch4_fixed512', list(range(10)), False, 512)]
    report = {'scope': 'source-free numerical diagnosis; no corpus queries, Gold, adoption or pipeline latency',
        'script_sha256': sha(__file__), 'runtime_sha256': sha(Path(__file__).parent / 'ettin_cpu.py'),
        'models': {}}
    for label, registration, record in zip(('int8', 'fp32'), args.registrations, registrations, strict=True):
        model = CPUReranker(record)
        result = {'registration_sha256': sha(registration), 'graph_sha256': record['graph_sha256'],
                  'upstream_revision': record['upstream']['revision'], 'profiles': {}}
        for length, documents in [('short', texts), ('capped512', [s + '\n' + (s + '\n') * 90 for s in texts])]:
            measurements = {}
            for name, order, single, padded_length in profiles:
                registered_padding(model.tokenizer, record['upstream'], length=padded_length)
                aligned_scores(model, query, documents, order, single)
                elapsed = []
                for _ in range(3):
                    started = time.perf_counter()
                    scores, details = aligned_scores(model, query, documents, order, single)
                    elapsed.append((time.perf_counter() - started) * 1000)
                if any(d['pad_id'] != 50283 for d in details):
                    raise ValueError('published padding ID not applied')
                measurements[name] = {'scores_aligned_to_original_pairs': scores, 'rank': rank(scores),
                                      'times_ms': elapsed, 'p50_ms': float(np.median(elapsed)), 'pad_id': 50283}
            baseline = measurements['batch4_dynamic']
            for name, measurement in measurements.items():
                measurement['max_abs_score_delta'] = float(np.max(np.abs(
                    np.array(measurement['scores_aligned_to_original_pairs']) - baseline['scores_aligned_to_original_pairs'])))
                measurement['rank_changed'] = measurement['rank'] != baseline['rank']
            result['profiles'][length] = measurements
        report['models'][label] = result
        del model
    if report['models']['int8']['upstream_revision'] != report['models']['fp32']['upstream_revision']:
        raise ValueError('precision comparison must use the same published model revision')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({label: {length: {name: {k: value[k] for k in ('max_abs_score_delta', 'rank_changed', 'p50_ms')}
        for name, value in profiles.items()} for length, profiles in model['profiles'].items()}
        for label, model in report['models'].items()}), flush=True)


if __name__ == '__main__':
    main()
