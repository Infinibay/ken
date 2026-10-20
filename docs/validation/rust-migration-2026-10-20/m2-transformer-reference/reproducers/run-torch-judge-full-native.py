"""Actual Torch judge numerical core, not public adapter acceptance."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import numpy as np

area = Path('/Users/andres/Projects/ken/.ken/rust-migration/m2-optional')
pre = area / 'preflight'
out = pre / 'torch-judge-full-core-native'
out.mkdir(exist_ok=False)
profiles = sorted((pre / 'judge-original-full-v2').glob('torch-*.json'))
assert len(profiles) == 6
registration = json.loads(profiles[0].read_text())['capture']['model_registration']
source = area / 'sources' / registration['model_id'].replace('/', '--') / registration['revision']
work = Path(tempfile.mkdtemp(prefix='ken-owned-torch-judge-full-', dir='/private/tmp'))
comparisons = []
try:
    (work / 'lib').mkdir()
    (work / 'snapshot').mkdir()
    (work / 'sentinel-bin').mkdir()
    libraries = json.loads((area / 'libtorch-macos-2.9.0/PREPARATION.json').read_text())['libraries']
    for row in libraries:
        target = work / 'lib' / row['name']
        shutil.copy2(area / 'libtorch-macos-2.9.0/lib' / row['name'], target)
        assert target.stat().st_size == row['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest() == row['sha256']
    for name in ('config.json', 'model.safetensors'):
        target = work / 'snapshot' / name
        shutil.copy2(source / name, target)
        with target.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        row = next(row for row in registration['files'] if row['path'] == name)
        assert target.stat().st_size == row['bytes'] and sha == row['sha256']
    binary = work / 'qwen-experiment'
    shutil.copy2(area / 'tensor-target-macos/release/qwen-experiment', binary)
    for profile in profiles:
        reference = json.loads(profile.read_text())['capture']
        requests = [{'dtype': feed['weight_dtype'].removeprefix('torch.'),
                     'device': feed['actual_device'].split(':')[0],
                     'input_ids': feed['inputs']['input_ids'], 'attention_mask': feed['inputs']['attention_mask'],
                     'projection_ids': feed['projection_ids'], 'include_hidden': False} for feed in reference['feeds']]
        requests_path = work / 'requests.json'
        requests_path.write_text(json.dumps({'cases': requests}) + '\n')
        target = out / profile.stem
        target.mkdir()
        shutil.copy2(requests_path, target / 'requests.json')
        env = {'PATH': str(work / 'sentinel-bin'), 'HOME': str(work), 'TMPDIR': str(work),
               'DYLD_LIBRARY_PATH': str(work / 'lib'), 'DYLD_PRINT_LIBRARIES': '1', 'OMP_NUM_THREADS': '2'}
        start = time.monotonic()
        process = subprocess.Popen([str(binary), str(work / 'snapshot'), str(requests_path)],
                                   cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=1800)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(0.5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(5)
        (target / 'native.stdout').write_bytes(stdout)
        (target / 'native.dyld.log').write_bytes(stderr)
        assert process.returncode == 0, (profile.name, process.returncode, stderr[-4000:])
        native = json.loads(stdout)
        assert len(native['cases']) == len(requests) and native['model_inference_accepted'] is False
        assert all(row['repeat_exact'] and row['hidden_f32'] is None for row in native['cases'])
        loaded = [match[1] for line in stderr.decode().splitlines()
                  if (match := re.fullmatch(r'dyld\[\d+\]: <[0-9A-F-]+> (/.+)', line))]
        assert loaded and 'python' not in stderr.decode().lower()
        assert all(path.startswith(('/usr/lib/', '/System/Library/', str(work) + '/')) for path in loaded)
        cases = []
        for request, expected in zip(reference['requests'], reference['results'], strict=True):
            if not expected['passed_original_call']:
                cases.append({'id': request['id'], 'original_error': expected['exception'],
                              'scope': 'Original adapter error retained; no numerical core invocation.'})
                continue
            first, last = expected['feed_range']
            actual = np.concatenate([np.asarray(row['scores_f32'], dtype=np.float32) for row in native['cases'][first:last]])
            wanted = np.frombuffer(bytes.fromhex(expected['scores_f32le_hex']), dtype='<f4')
            assert actual.shape == wanted.shape and np.isfinite(actual).all()
            error = float(np.max(np.abs(actual - wanted)))
            cases.append({'id': request['id'], 'passed': error <= 1e-5, 'max_abs_error': error, 'fixed_tolerance': 1e-5})
        record = {'profile': profile.name, 'passed': all(row.get('passed', True) for row in cases), 'cases': cases,
                  'execution_s': time.monotonic() - start, 'actual_library_paths': loaded,
                  'original_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
                  'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'libraries': libraries,
                  'outside_checkout': True, 'model_inference_accepted': False,
                  'scope': 'Raw yes-minus-no numerical core only with real observed feeds. No public text/state adapter acceptance or macOS kernel child-exec claim.'}
        (target / 'comparison.json').write_text(json.dumps(record, indent=2) + '\n')
        comparisons.append(record)
        (out / 'summary.json').write_text(json.dumps({'passed': all(row['passed'] for row in comparisons),
            'profiles': comparisons, 'model_inference_accepted': False}, indent=2) + '\n')
        print(json.dumps({'profile': profile.name, 'passed': record['passed'],
                          'max_abs_error': max(row.get('max_abs_error', 0.) for row in cases),
                          'execution_s': record['execution_s']}), flush=True)
        assert record['passed']
finally:
    shutil.rmtree(work)
assert len(comparisons) == 6
print(json.dumps({'passed': True, 'profiles': 6, 'observed_feeds': 78, 'model_inference_accepted': False}), flush=True)
