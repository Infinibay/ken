"""Capture registered static-model behavior from an isolated frozen Python process."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

TOLERANCES = {
    'float32': {'atol': 2e-6, 'rtol': 1e-5, 'cosine_min': .999999},
    'float16': {'atol': 2e-4, 'rtol': 2e-3, 'cosine_min': .99999},
}


def model_cases() -> list[dict]:
    cases = []
    for name, text in [('empty', ''), ('spaces', ' \t\n'),
                       ('spanish', '¿Dónde se guarda la configuración del usuario?'),
                       ('nfc', 'café'), ('nfd', 'cafe\u0301'), ('emoji', '🙂🚀'),
                       ('code', 'def save_config(path):\n    config.value = read_json(path)'),
                       ('unknown', '[UNK]'), ('pad', '[PAD]')]:
        cases.append({'id': name, 'calls': [{'op': 'tokens', 'text': text, 'max_length': None},
                                          {'op': 'count', 'text': text},
                                          {'op': 'query', 'text': text}]})
    for count in [511, 512, 513]:
        text = 'alpha ' * count
        cases.append({'id': f'tokens-{count}', 'calls': [
            {'op': 'tokens', 'text': text, 'max_length': None},
            {'op': 'tokens', 'text': text, 'max_length': 512},
            {'op': 'count', 'text': text}, {'op': 'query', 'text': text}]})
    cases.extend([
        {'id': 'mixed-empty', 'calls': [{'op': 'passages', 'texts': ['alpha beta', '', '[PAD]', 'café']}]},
        {'id': 'empty-batch', 'calls': [{'op': 'passages', 'texts': []}]},
        {'id': 'cache-history', 'calls': [{'op': 'passages', 'texts': ['alpha', 'alpha beta']},
                                         {'op': 'passages', 'texts': ['alpha', 'alpha beta', '']},
                                         {'op': 'query', 'text': 'alpha'},
                                         {'op': 'passages', 'texts': ['alpha\u001c', 'beta', 'beta']}]},
        {'id': 'unicode-prefix', 'calls': [
            {'op': 'tokens', 'text': '🙂' * 3583 + ' alpha', 'max_length': 512},
            {'op': 'tokens', 'text': '🙂' * 3583 + ' alpha', 'max_length': None}]},
    ])
    for count in [1024, 1025]:
        cases.append({'id': f'batch-{count}', 'calls': [
            {'op': 'passages', 'texts': ['alpha beta'] * 1023 + [''] + ['alpha beta'] * (count - 1024)}]})
    return cases


# This child imports exclusively from Reference.root/src; no native implementation
# or expected outputs participate in producing the oracle.
_CHILD = r'''
import json, sys, time
from pathlib import Path
from importlib.metadata import version
import ken
from ken.model_assets import ModelAssets
from ken.embedder.model2vec_backend import RegisteredStaticEncoder
request = json.load(sys.stdin)
root = Path(request['reference']).resolve()
if not Path(ken.__file__).resolve().is_relative_to(root / 'src'):
    raise ValueError('reference import escaped frozen tree')
versions = {p: version(p) for p in ('numpy', 'model2vec', 'tokenizers', 'safetensors')}
if versions['model2vec'] != '0.9.0':
    raise ValueError('model2vec 0.9.0 is required')
assets = ModelAssets.from_dict(request['registration'])
assets.verify(Path(request['snapshot']))
results = []
for case in request['cases']:
    start = time.monotonic_ns()
    encoder = RegisteredStaticEncoder(Path(request['snapshot']), request['registration'])
    loaded = time.monotonic_ns()
    values = []
    for call in case['calls']:
        op = call['op']
        if op == 'tokens':
            value = encoder.model.tokenize([call['text']], max_length=call['max_length'])[0]
        elif op == 'count':
            value = encoder.token_count(call['text'])
        elif op == 'query':
            value = encoder.embed_query(call['text']).tolist()
        elif op == 'passages':
            value = [v.tolist() for v in encoder.embed_passages(call['texts'])]
        else:
            raise ValueError('unknown model operation')
        values.append(value)
    results.append({'id': case['id'], 'calls': values,
                    'load_ns': loaded - start, 'inference_ns': time.monotonic_ns() - loaded})
print(json.dumps({'oracle': {'frozen_import': True, 'runtime': versions},
                  'assets_fingerprint': assets.fingerprint, 'identity': encoder.identity,
                  'dimension': encoder.dim, 'results': results}, allow_nan=False))
'''


def _verify_snapshot(snapshot: Path, registration: dict) -> None:
    if snapshot.name != registration['revision'] or not snapshot.is_dir():
        raise ValueError('registered revision directory required')
    for name, expected in registration['artifacts'].items():
        path = snapshot / name
        if (not path.is_file() or path.stat().st_size != expected['bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']):
            raise ValueError(f'registered artifact changed: {name}')


def _pack_vectors(vectors: list[list[float]]) -> dict:
    unique, indices, seen = [], [], {}
    for vector in vectors:
        key = tuple(vector)
        if key not in seen:
            seen[key] = len(unique)
            unique.append(vector)
        indices.append(seen[key])
    return {'vectors': unique, 'rows': indices}


def capture(reference: Reference, snapshot: Path, output: Path, *,
            registration: dict | None = None, cases: list[dict] | None = None) -> dict:
    """Verify inputs, run the frozen encoder and retain every ordered result."""
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('reference source drift')
    if registration is None:
        registration = json.loads((reference.root / 'src/ken/embedder/data/potion-code-16M-v2.json').read_text())
    snapshot = snapshot.absolute()
    _verify_snapshot(snapshot, registration)
    cases = model_cases() if cases is None else cases
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('distinct nonempty model cases required')
    with tempfile.TemporaryDirectory(prefix='ken-model-oracle-') as directory:
        sandbox = Path(directory)
        env = reference_env(reference, sandbox)
        env.update(HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
        child = subprocess.run([str(reference.python), '-c', _CHILD], cwd=sandbox, env=env,
                               input=json.dumps({'reference': str(reference.root), 'snapshot': str(snapshot),
                                                 'registration': registration, 'cases': cases}),
                               text=True, capture_output=True, timeout=180)
        if child.returncode:
            raise ValueError(f'frozen model capture failed: {child.stderr}')
    result = json.loads(child.stdout)
    for case, actual in zip(cases, result['results'], strict=True):
        for i, call in enumerate(case['calls']):
            if call['op'] == 'passages':
                actual['calls'][i] = _pack_vectors(actual['calls'][i])
    if verify_reference(reference.root, reference.manifest_path):
        raise ValueError('reference source drift during capture')
    _verify_snapshot(snapshot, registration)
    result.update(format='ken-model-oracle/1', registration=registration, cases=cases,
                  tolerances=TOLERANCES, reference_fingerprint=reference.fingerprint)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False) + '\n')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = capture(Reference.load(args.reference), args.snapshot, args.out)
    print(json.dumps({'passed': True, 'cases': len(result['cases']),
                      'dimension': result['dimension'], 'assets_fingerprint': result['assets_fingerprint']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
