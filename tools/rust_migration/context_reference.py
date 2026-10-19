"""Capture contextual policy and raw vectors only from verified frozen Python."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

TOLERANCES = {'atol': 2e-6, 'rtol': 1e-5, 'cosine_min': .999999}
CPU_WARNING = 'onnxruntime cpuid_info warning: Unknown CPU vendor. cpuinfo_vendor value: 0\n'


def stderr_errors(value: str, system: str) -> list[str]:
    # The warning depends on CPU identification. Its absence or one exact line
    # is allowed on Linux; every other byte/count and every macOS byte fails.
    return [] if value == '' or (system == 'Linux' and value == CPU_WARNING) else ['unexpected contextual stderr']


def context_cases() -> list[dict]:
    def text_case(name, text, kind='query'):
        call = {'op': 'query', 'text': text} if kind == 'query' else {'op': 'passages', 'texts': [text]}
        return {'id': name, 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': kind, 'text': text}, call]}
    result = [
        {'id': 'empty-passages', 'prepare': False, 'calls': [{'op': 'passages', 'texts': []}]},
        text_case('empty-query', ''), text_case('whitespace-query', ' \t\n'),
        text_case('empty-passage', '', 'passage'),
        text_case('spanish-query', '¿Dónde se guarda la configuración del usuario?'),
        text_case('code-query', 'def save_config(path):\n    config.value = read_json(path)'),
        {'id': 'unicode-canonical', 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': 'passage', 'text': 'café'},
            {'op': 'tokens', 'kind': 'passage', 'text': 'cafe\u0301'},
            {'op': 'passages', 'texts': ['café', 'cafe\u0301']}]},
        text_case('emoji-and-nul', '🙂🚀\x00 configuration'),
        {'id': 'query-versus-passage', 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': 'query', 'text': 'alpha beta'},
            {'op': 'tokens', 'kind': 'passage', 'text': 'alpha beta'},
            {'op': 'query', 'text': 'alpha beta'}, {'op': 'passages', 'texts': ['alpha beta']}]},
        text_case('serialized-special-literals', '[CLS] [SEP] [PAD] [UNK]', 'passage'),
        {'id': 'mixed-passages', 'prepare': True, 'calls': [
            {'op': 'passages', 'texts': ['red', '', 'red blue', ' \t', 'red']}]},
        {'id': 'repeated-history', 'prepare': True, 'calls': [
            {'op': 'query', 'text': 'alpha beta'}, {'op': 'query', 'text': 'alpha beta'},
            {'op': 'passages', 'texts': ['alpha beta', 'beta alpha', 'alpha beta']}]},
        text_case('unicode-whitespace', 'alpha\u0085beta\u00a0gamma\u2003delta'),
    ]
    for kind, overhead in [('passage', 2), ('query', 10)]:
        for length in (511, 512, 513):
            case = text_case(f'{kind}-boundary{length}', 'alpha '*(length-overhead), kind)
            case['untruncated_tokens'] = length
            result.append(case)
    result.append(text_case('long4097', 'alpha '*4097, 'passage'))
    return result


def snapshot_state(snapshot: Path, definition: dict) -> dict:
    if set(definition['artifacts']) != {'onnx/model.onnx', 'tokenizer.json'}:
        raise ValueError('context requires graph and tokenizer artifacts')
    if not snapshot.is_dir() or snapshot.name != definition['revision']:
        raise ValueError('artifact snapshot revision mismatch')
    result = {}
    for name, declared in definition['artifacts'].items():
        path = snapshot / name
        if not path.is_file(): raise ValueError(f'nonregular or missing artifact: {name}')
        size = path.stat().st_size
        if size != declared['bytes']: raise ValueError(f'artifact size mismatch: {name}')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != declared['sha256']: raise ValueError(f'artifact hash mismatch: {name}')
        result[name] = {'bytes': size, 'sha256': digest}
    return result


_CHILD = r'''
import json, platform, resource, sys, time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from tokenizers import Tokenizer
import ken
import ken.embedder.contextual_onnx as implementation
from ken.model_assets import ModelAssets
request = json.load(sys.stdin)
root = Path(request['reference'])
for imported in (ken, implementation):
    if not Path(imported.__file__).resolve().is_relative_to(root / 'src'):
        raise ValueError('reference import escaped frozen tree')
definition = request['definition']
model = implementation.ContextModel(ModelAssets.from_dict(definition),
    definition['query_prefix'], definition['document_projection'])
def peak():
    if sys.platform.startswith('linux'):
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmHWM:'): return int(line.split()[1])*1024
        raise ValueError('VmHWM absent')
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
results = []
boundaries = {}
for case in request['cases']:
    started = time.monotonic_ns()
    encoder = implementation.ContextEncoder(model, snapshot=Path(request['snapshot']))
    if case['prepare']: encoder._load()
    if 'untruncated_tokens' in case:
        unbounded = Tokenizer.from_str(encoder._tokenizer.to_str())
        unbounded.no_truncation()
        call = case['calls'][0]
        text = model.query_prefix + call['text'] if call['kind'] == 'query' else call['text']
        count = len(unbounded.encode(text).ids)
        if count != case['untruncated_tokens']: raise ValueError('boundary does not have declared raw length')
        boundaries[case['id']] = count
    loaded = time.monotonic_ns()
    loaded_peak = peak()
    calls = []
    for call in case['calls']:
        if call['op'] == 'tokens':
            encoder._load()
            if call['kind'] not in ('query', 'passage'): raise ValueError('unknown context input kind')
            text = model.query_prefix + call['text'] if call['kind'] == 'query' else call['text']
            tokens = encoder._tokenizer.encode(text)
            value = {'ids': tokens.ids, 'attention_mask': tokens.attention_mask}
        elif call['op'] == 'query': value = encoder.embed_query(call['text']).tolist()
        elif call['op'] == 'passages': value = [v.tolist() for v in encoder.embed_passages(call['texts'])]
        else: raise ValueError('unknown context operation')
        calls.append(value)
    results.append({'id': case['id'], 'calls': calls, 'load_ns': loaded-started,
        'inference_ns': time.monotonic_ns()-loaded, 'peak_after_load_bytes': loaded_peak,
        'peak_after_inference_bytes': peak(), 'session_loaded': encoder._session is not None,
        'providers': encoder._session.get_providers() if encoder._session is not None else []})
print(json.dumps({'oracle': {'frozen_import': True,
    'import_relative': str(Path(implementation.__file__).relative_to(root)),
    'runtime': {p: version(p) for p in ('numpy','onnxruntime','tokenizers','onnx')}},
    'platform': platform.system(), 'architecture': platform.machine(), 'dimension': 768,
    'spec': asdict(model.spec), 'spec_key': model.spec.key,
    'tokenizer_revision': model.spec.tokenizer_revision, 'boundary_characterization': boundaries,
    'results': results}, allow_nan=False))
'''


def capture(reference: Reference, snapshot: Path, output: Path, *,
            definition: dict | None = None, cases: list[dict] | None = None) -> dict:
    if verify_reference(reference.root, reference.manifest_path): raise ValueError('reference source drift')
    if definition is None:
        definition = json.loads((reference.root / 'src/ken/embedder/data/code-context-int8.json').read_text())
    snapshot = snapshot.absolute()
    before = snapshot_state(snapshot, definition)
    cases = context_cases() if cases is None else cases
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('distinct nonempty context histories required')
    with tempfile.TemporaryDirectory(prefix='ken-context-oracle-') as directory:
        sandbox = Path(directory)
        env = reference_env(reference, sandbox)
        env.update(TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1')
        child = subprocess.run([str(reference.python), '-c', _CHILD], cwd=sandbox, env=env,
            input=json.dumps({'reference': str(reference.root), 'snapshot': str(snapshot),
                              'definition': definition, 'cases': cases}),
            text=True, capture_output=True, timeout=600)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode: raise ValueError(f'frozen context capture failed: {child.stderr}')
    result = json.loads(child.stdout)
    if stderr_errors(child.stderr, result['platform']):
        raise ValueError(f'unexpected frozen context stderr: {child.stderr}')
    if before != snapshot_state(snapshot, definition): raise ValueError('artifact drift during context capture')
    if verify_reference(reference.root, reference.manifest_path): raise ValueError('reference drift during context capture')
    result['oracle']['stderr'] = child.stderr
    result.update(format='ken-context-oracle/1', definition=definition, artifacts=before,
                  cases=cases, tolerances=TOLERANCES, reference_fingerprint=reference.fingerprint)
    output.write_text(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False)+'\n')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = capture(Reference.load(args.reference), args.snapshot, args.out)
    print(json.dumps({'passed': True, 'cases': len(result['cases']), 'platform': result['platform']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
