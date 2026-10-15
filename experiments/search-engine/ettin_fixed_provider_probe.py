"""One source-free17M static-shape eligibility experiment for CoreML.

Same registered INT8 weights/head; pad the final batch with valid duplicate
pairs and discard their scores. This does not change the CPU quality benchmark.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import onnx
from onnxruntime.tools.make_dynamic_shape_fixed import make_input_shape_fixed, fix_output_shapes

import ettin_provider_probe as probe
from ettin_cpu import CPUReranker, sha, registered_padding


class FixedInputReranker(CPUReranker):
    def __init__(self, registration):
        if registration.get('fixed_input_shape') != [4, 512]:
            raise ValueError('expected registered4x512 specialization')
        super().__init__(registration)
        registered_padding(self.tokenizer,registration['upstream'],length=512)

    def score(self, query, texts):
        scores = []
        details = {'token_ms': 0, 'inference_ms': 0, 'pair_tokens': []}
        for start in range(0, len(texts), 4):
            batch = texts[start:start + 4]
            n = len(batch)
            values, timing = super().score(query, batch + [batch[-1]] * (4 - n))
            scores.extend(values[:n])
            for field in ('token_ms', 'inference_ms'):
                details[field] += timing[field]
            details['pair_tokens'].extend(timing['pair_tokens'][:n])
        return scores, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provider', choices=['cpu', 'coreml'])
    args = parser.parse_args()
    if args.provider:
        probe.CPUReranker = FixedInputReranker
        probe.worker(args)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    registration = json.loads(args.registration.read_text())
    if sha(registration['graph']) != registration['graph_sha256']:
        raise ValueError('registered graph changed')
    model = onnx.load(registration['graph'])
    for name in ('input_ids', 'attention_mask'):
        make_input_shape_fixed(model.graph, name, [4, 512])
    fix_output_shapes(model)
    onnx.checker.check_model(model)
    graph = (args.output / 'model-static4x512.onnx').resolve()
    onnx.save(model, graph)
    specialized = {**registration, 'graph': str(graph), 'graph_sha256': sha(graph), 'graph_bytes': graph.stat().st_size,
        'source_registration_sha256': sha(args.registration), 'source_graph_sha256': registration['graph_sha256'],
        'fixed_input_shape': [4, 512], 'scope': 'shape-only specialization; synthetic parity/eligibility pending'}
    regpath = (args.output / 'static-registration.json').resolve()
    regpath.write_text(json.dumps(specialized, indent=2))
    trials = {}
    for provider in ('cpu', 'coreml'):
        directory = args.output / provider
        command = [sys.executable, str(Path(__file__).resolve()), '--registration', str(regpath),
            '--provider', provider, '--output', str(directory)]
        try:
            with (args.output / (provider + '.log')).open('w') as log:
                result = subprocess.run(command, stdout=log, stderr=log, timeout=60, check=False)
            trials[provider] = json.loads((directory / 'result.json').read_text()) if result.returncode == 0 else {
                'ok': False, 'reason': 'trial failed', 'exit_code': result.returncode}
        except subprocess.TimeoutExpired:
            trials[provider] = {'ok': False, 'reason': 'trial deadline exceeded'}
        print(json.dumps({'provider': provider, 'ok': trials[provider]['ok']}), flush=True)
    (args.output / 'report.json').write_text(json.dumps({'scope': 'synthetic static17M probe; not corpus quality',
        'source_registration_sha256': sha(args.registration), 'static_registration_sha256': sha(regpath),
        'script_sha256': sha(__file__), 'trials': trials}, indent=2))


if __name__ == '__main__':
    main()
