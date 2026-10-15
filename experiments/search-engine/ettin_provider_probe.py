"""Source-free CPU/CoreML trials, separate from the fixed CPU quality benchmark.

Each provider runs in an isolated child with a deadline; an unusable accelerator
never removes the CPU option. This is a runtime experiment, not product routing.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort

from ettin_cpu import CPUReranker, cpu_options, sha


def provider_choice(cpu, accelerated, profile):
    if not cpu.get('ok'):
        raise ValueError('mandatory CPU baseline unavailable')
    if not accelerated.get('ok') or not accelerated.get('accelerator_nodes', 0):
        return 'CPUExecutionProvider'
    a, b = cpu['profiles'][profile], accelerated['profiles'][profile]
    if (not np.allclose(a['scores'], b['scores'], rtol=1e-5, atol=2e-5)
            or sorted(range(10), key=lambda i: (-a['scores'][i], i)) !=
               sorted(range(10), key=lambda i: (-b['scores'][i], i))):
        return 'CPUExecutionProvider'
    # A fixed noise margin prevents switching for negligible differences.
    return 'CoreMLExecutionProvider' if b['p50_ms'] < a['p50_ms'] / 1.05 else 'CPUExecutionProvider'


def worker(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    registration = json.loads(args.registration.read_text())
    started = time.perf_counter()
    model = CPUReranker(registration)
    providers = ['CPUExecutionProvider']
    if args.provider == 'coreml':
        cache = (output / registration['graph_sha256'] / 'cache').resolve()
        providers = [('CoreMLExecutionProvider', {'ModelFormat': 'MLProgram',
            'MLComputeUnits': 'ALL', 'RequireStaticInputShapes': '0', 'EnableOnSubgraphs': '0',
            'AllowLowPrecisionAccumulationOnGPU': '0', 'ModelCacheDirectory': str(cache)}),
            'CPUExecutionProvider']
        model.session = ort.InferenceSession(registration['graph'], sess_options=cpu_options(), providers=providers)
    load_ms = (time.perf_counter() - started) * 1000
    snippets = ['def get(key): return cache[key]', 'def put(key, value): cache[key] = value',
        'def parse(text): return json.loads(text)', 'def read(path): return path.read_text()',
        'def sort(items): return sorted(items)', 'def validate(x): return x is not None',
        'def render(text): return "<p>" + text + "</p>"', 'def save(value): disk.write(value)',
        'def digest(data): return sha256(data)', 'DEFAULT_PORT = 8080']
    query = 'find code that stores and retrieves a value by key'
    record = {'ok': True, 'scope': 'synthetic provider experiment only; no repository queries or quality labels',
        'registration_sha256': sha(args.registration), 'provider_requested': args.provider,
        'provider_actual': model.session.get_providers(), 'load_ms': load_ms, 'profiles': {}}
    for profile, texts in [('short', snippets), ('capped512', [s + '\n' + (s + '\n') * 90 for s in snippets])]:
        model.score(query, texts)
        timings = []
        for _ in range(3):
            start = time.perf_counter()
            scores, details = model.score(query, texts)
            timings.append((time.perf_counter() - start) * 1000)
        record['profiles'][profile] = {'times_ms': timings, 'p50_ms': float(np.median(timings)),
            'scores': scores, 'pair_tokens': details['pair_tokens']}
    # Attribution is collected AFTER timing; profiling overhead is not in latency.
    options = cpu_options()
    options.enable_profiling = True
    options.profile_file_prefix = str((output / 'ort-profile').resolve())
    traced = ort.InferenceSession(registration['graph'], sess_options=options, providers=providers)
    original = model.session
    model.session = traced
    model.score(query, snippets)
    trace_path = Path(traced.end_profiling())
    model.session = original
    trace = json.loads(trace_path.read_text())
    from collections import Counter
    counts = Counter(e.get('args', {}).get('provider') for e in trace
        if e.get('cat') == 'Node' and e.get('args', {}).get('provider'))
    record['profile_node_provider_counts'] = dict(counts)
    record['accelerator_nodes'] = counts.get('CoreMLExecutionProvider', 0)
    (output / 'result.json').write_text(json.dumps(record, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--registration', type=Path)
    parser.add_argument('--provider', choices=['cpu', 'coreml'])
    args = parser.parse_args()
    if args.provider:
        worker(args)
        return
    if args.workspace is None:
        parser.error('--workspace is required for the comparison controller')
    args.output.mkdir(parents=True, exist_ok=False)
    available = ort.get_available_providers()
    summary = {'scope': 'synthetic isolated CPU/CoreML comparison; no production selection or quality claim',
        'available': available, 'noise_margin': 1.05, 'trial_deadline_seconds': 60,
        'script_sha256': sha(__file__), 'models': {}}
    for size in ('17m', '32m', '68m'):
        reg = args.workspace / 'output/models/ettin-all-onnx-v98' / size / 'assembly.json'
        trials = {}
        for provider in ('cpu', 'coreml'):
            if provider == 'coreml' and 'CoreMLExecutionProvider' not in available:
                trials[provider] = {'ok': False, 'reason': 'provider unavailable'}
                continue
            directory = args.output / (size + '-' + provider)
            command = [sys.executable, str(Path(__file__).resolve()), '--registration', str(reg),
                '--provider', provider, '--output', str(directory)]
            try:
                with (args.output / (size + '-' + provider + '.log')).open('w') as log:
                    completed = subprocess.run(command, stdout=log, stderr=log, timeout=60, check=False)
                trials[provider] = json.loads((directory / 'result.json').read_text()) if completed.returncode == 0 else {
                    'ok': False, 'reason': 'provider trial failed', 'exit_code': completed.returncode}
            except subprocess.TimeoutExpired:
                trials[provider] = {'ok': False, 'reason': 'provider trial deadline exceeded'}
            print(json.dumps({'size': size, 'provider': provider, 'ok': trials[provider]['ok']}), flush=True)
        summary['models'][size] = {'trials': trials, 'suggested_provider_by_profile': {
            p: provider_choice(trials['cpu'], trials['coreml'], p) for p in ('short', 'capped512')}}
        (args.output / 'report.json').write_text(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
