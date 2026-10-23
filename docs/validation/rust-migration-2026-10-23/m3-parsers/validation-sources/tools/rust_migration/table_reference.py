"""Capture the existing NPZ encoder from a verified, isolated Python tree."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

TOLERANCES = {'atol': 2e-6, 'rtol': 1e-5, 'cosine_min': .999999}


def table_cases() -> list[dict]:
    cases = []
    for name, text in [('empty', ''), ('spaces', ' \t\n'),
                       ('spanish', '¿Dónde se guarda la configuración del usuario?'),
                       ('nfc', 'café'), ('nfd', 'cafe\u0301'), ('emoji', '🙂🚀'),
                       ('code', 'def save_config(path):\n    config.value = read_json(path)'),
                       ('unknown', '[UNK]'), ('pad', '[PAD]')]:
        cases.append({'id': name, 'calls': [{'op': 'tokens', 'text': text},
                                          {'op': 'count', 'text': text},
                                          {'op': 'query', 'text': text}]})
    for count in (512, 513, 4097):
        text = 'alfa ' * count
        cases.append({'id': f'long-{count}', 'calls': [{'op': 'tokens', 'text': text},
                                                     {'op': 'count', 'text': text},
                                                     {'op': 'query', 'text': text}]})
    cases.extend([
        {'id': 'mixed-empty', 'calls': [
            {'op': 'passages', 'texts': ['', 'alfa beta', '', '', 'gamma', '']},
            {'op': 'queries', 'texts': ['', 'alfa beta', '', '', 'gamma', '']}]},
        {'id': 'empty-batch', 'calls': [{'op': 'passages', 'texts': []},
                                       {'op': 'queries', 'texts': []}]},
        {'id': 'batching', 'calls': [{'op': 'query', 'text': 'alfa beta'},
                                    {'op': 'passages', 'texts': ['gamma', 'alfa beta', 'delta']},
                                    {'op': 'queries', 'texts': ['alfa beta']}]},
        {'id': 'repeated-order', 'calls': [{'op': 'passages', 'texts': [
            'alfa beta gamma', 'gamma beta alfa', 'alfa alfa beta', 'alfa beta gamma']}]},
    ])
    return cases


_CHILD = r'''
import hashlib, json, resource, sys, time
from importlib.metadata import version
from pathlib import Path
import ken
from ken.embedder.static_head import StaticHeadEmbedder
request = json.load(sys.stdin)
if not Path(ken.__file__).resolve().is_relative_to(Path(request['reference']) / 'src'):
    raise ValueError('reference import escaped frozen tree')
artifact = Path(request['artifact'])
if hashlib.sha256(artifact.read_bytes()).hexdigest() != request['sha256']:
    raise ValueError('artifact changed before loading')
def peak():
    if sys.platform.startswith('linux'):
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmHWM:'):
                return int(line.split()[1]) * 1024
        raise ValueError('VmHWM absent')
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
results = []
for case in request['cases']:
    started = time.monotonic_ns()
    encoder = StaticHeadEmbedder('ken/static-qwen3-r512-v2', path=artifact)
    dimension = encoder.dim
    loaded = time.monotonic_ns()
    loaded_peak = peak()
    values = []
    for call in case['calls']:
        op = call['op']
        if op == 'tokens':
            value = encoder._tok.encode(call['text'], add_special_tokens=False).ids
        elif op == 'count':
            value = encoder.token_count(call['text'])
        elif op == 'query':
            value = encoder.embed_query(call['text']).tolist()
        elif op in ('passages', 'queries'):
            method = encoder.embed_passages if op == 'passages' else encoder.embed_queries
            value = [v.tolist() for v in method(call['texts'])]
        else:
            raise ValueError('unknown table operation')
        values.append(value)
    results.append({'id': case['id'], 'calls': values, 'load_ns': loaded-started,
                    'inference_ns': time.monotonic_ns()-loaded,
                    'peak_after_load_bytes': loaded_peak,
                    'peak_after_inference_bytes': peak()})
if hashlib.sha256(artifact.read_bytes()).hexdigest() != request['sha256']:
    raise ValueError('artifact changed during inference')
print(json.dumps({'oracle': {'frozen_import': True, 'runtime': {
    p: version(p) for p in ('numpy', 'tokenizers')}}, 'dimension': dimension,
    'meta': encoder.meta, 'results': results}, allow_nan=False))
'''


def capture(reference: Reference, artifact: Path, output: Path, *,
            cases: list[dict] | None = None, expected_sha256: str | None = None) -> dict:
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('reference source drift')
    artifact = artifact.resolve(strict=True)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if expected_sha256 is not None and expected_sha256 != digest:
        raise ValueError('artifact hash mismatch')
    cases = table_cases() if cases is None else cases
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('distinct nonempty table cases required')
    with tempfile.TemporaryDirectory(prefix='ken-table-oracle-') as directory:
        sandbox = Path(directory)
        env = reference_env(reference, sandbox)
        env.update(TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1')
        child = subprocess.run([str(reference.python), '-c', _CHILD], cwd=sandbox, env=env,
                               input=json.dumps({'reference': str(reference.root),
                                                 'artifact': str(artifact), 'sha256': digest,
                                                 'cases': cases}), text=True,
                               capture_output=True, timeout=180)
        if child.returncode:
            raise ValueError(f'frozen table capture failed: {child.stderr}')
    result = json.loads(child.stdout)
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != digest:
        raise ValueError('artifact changed during capture')
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('reference source drift during capture')
    result.update(format='ken-table-oracle/1', cases=cases, tolerances=TOLERANCES,
                  artifact={'sha256': digest, 'bytes': artifact.stat().st_size},
                  reference_fingerprint=reference.fingerprint)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + '\n')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = capture(Reference.load(args.reference), args.artifact, args.out)
    print(json.dumps({'passed': True, 'cases': len(result['cases']),
                      'dimension': result['dimension'], 'artifact': result['artifact']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
