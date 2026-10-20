"""Replay real original MLX feeds; this does not implement a text adapter."""
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
out = pre / 'mlx-full-core-native'
out.mkdir(exist_ok=False)
primitive = json.loads((pre / 'mlx-primitive-native-comparison.json').read_text())
assert primitive['passed']
comparisons = []
for adapter, folder in [('encoder', 'mlx-original-full'), ('judge', 'judge-original-full-v2')]:
    profiles = sorted((pre / folder).glob('*.json' if adapter == 'encoder' else 'mlx-mlx-*.json'))
    assert len(profiles) == 3
    first = json.loads(profiles[0].read_text())
    first = first['capture'] if adapter == 'judge' else first
    registration = first['model_registration']
    source = area / 'sources' / registration['model_id'].replace('/', '--') / registration['revision']
    work = Path(tempfile.mkdtemp(prefix=f'ken-owned-mlx-full-{adapter}-', dir='/private/tmp'))
    try:
        (work / 'lib').mkdir()
        (work / 'snapshot').mkdir()
        (work / 'sentinel-bin').mkdir()
        assert not work.is_relative_to(area.parents[2])
        for row in primitive['core_files']:
            dst = work / 'lib' / row['name']
            shutil.copy2(area / 'oracle-mlx-macos-locked/lib/python3.12/site-packages/mlx/lib' / row['name'], dst)
            assert dst.stat().st_size == row['bytes'] and hashlib.sha256(dst.read_bytes()).hexdigest() == row['sha256']
        for name in ('config.json', 'model.safetensors'):
            dst = work / 'snapshot' / name
            shutil.copy2(source / name, dst)
            with dst.open('rb') as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            row = next(row for row in registration['files'] if row['path'] == name)
            assert dst.stat().st_size == row['bytes'] and sha == row['sha256']
        binary = work / 'qwen-mlx-experiment'
        shutil.copy2(area / 'mlx-target-macos/release/qwen-mlx-experiment', binary)
        for profile in profiles:
            reference = json.loads(profile.read_text())
            reference = reference['capture'] if adapter == 'judge' else reference
            requests = []
            for feed in reference['feeds']:
                request = {key: feed[key] for key in ('input_ids', 'real_lengths', 'original_indices')}
                request.update(dtype=reference['settings']['dtype'], include_hidden=False)
                if adapter == 'judge':
                    request['projection_ids'] = feed['projection_ids']
                requests.append(request)
            request_path = work / 'requests.json'
            request_path.write_text(json.dumps({'cases': requests}) + '\n')
            target = out / (adapter + '-' + profile.stem)
            target.mkdir()
            shutil.copy2(request_path, target / 'requests.json')
            env = {'PATH': str(work / 'sentinel-bin'), 'HOME': str(work), 'TMPDIR': str(work),
                   'DYLD_LIBRARY_PATH': str(work / 'lib'), 'DYLD_PRINT_LIBRARIES': '1'}
            start = time.monotonic()
            process = subprocess.Popen([str(binary), str(work / 'snapshot'), str(request_path)], cwd=work,
                                       env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
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
            assert native['device'] == 'Device(gpu, 0)' and native['model_inference_accepted'] is False
            assert len(native['cases']) == len(requests)
            assert all(case['repeat_exact'] and case['hidden_f32'] is None for case in native['cases'])
            loaded = [match[1] for line in stderr.decode().splitlines()
                      if (match := re.fullmatch(r'dyld\[\d+\]: <[0-9A-F-]+> (/.+)', line))]
            assert loaded and 'python' not in stderr.decode().lower()
            assert all(path.startswith(('/usr/lib/', '/System/Library/', str(work) + '/')) for path in loaded)
            cases = []
            for request, expected in zip(reference['requests'], reference['results'], strict=True):
                if not expected['passed_original_call']:
                    assert adapter == 'judge'
                    cases.append({'id': request['id'], 'original_error': expected['exception'],
                                  'scope': 'Original adapter error retained; not executed by numerical core.'})
                    continue
                first_feed, last_feed = expected['feed_range']
                if adapter == 'encoder':
                    values = np.empty(expected['shape'], dtype=np.float32)
                    indices = []
                    for feed, actual in zip(reference['feeds'][first_feed:last_feed], native['cases'][first_feed:last_feed], strict=True):
                        rows = np.asarray(actual['vectors_f32'], dtype=np.float32).reshape(-1, 1024)
                        assert actual['original_indices'] == feed['original_indices']
                        values[feed['original_indices']] = rows
                        indices.extend(feed['original_indices'])
                    assert sorted(indices) == list(range(len(request['texts'])))
                    wanted = np.frombuffer(bytes.fromhex(expected['vectors_f32le_hex']), dtype='<f4').reshape(expected['shape'])
                    tolerance = 1e-6
                else:
                    values = np.concatenate([np.asarray(actual['scores_f32'], dtype=np.float32)
                                             for actual in native['cases'][first_feed:last_feed]])
                    wanted = np.frombuffer(bytes.fromhex(expected['scores_f32le_hex']), dtype='<f4')
                    tolerance = 1e-5
                assert values.shape == wanted.shape and np.isfinite(values).all()
                error = float(np.max(np.abs(values - wanted)))
                cases.append({'id': request['id'], 'passed': error <= tolerance,
                              'max_abs_error': error, 'fixed_tolerance': tolerance})
            record = {'profile': profile.name, 'adapter': adapter, 'passed': all(c.get('passed', True) for c in cases),
                      'cases': cases, 'execution_s': time.monotonic() - start, 'actual_library_paths': loaded,
                      'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'core_files': primitive['core_files'],
                      'original_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(), 'outside_checkout': True,
                      'model_inference_accepted': False,
                      'scope': 'Real numerical core only; captured original tokens/lengths are inputs. Public text/lifecycle adapter acceptance remains mandatory; macOS load audit is not a kernel child-exec trace.'}
            (target / 'comparison.json').write_text(json.dumps(record, indent=2) + '\n')
            comparisons.append(record)
            (out / 'summary.json').write_text(json.dumps({'passed': all(r['passed'] for r in comparisons),
                'profiles': comparisons, 'model_inference_accepted': False}, indent=2) + '\n')
            print(json.dumps({'profile': profile.name, 'adapter': adapter, 'passed': record['passed'],
                              'max_abs_error': max(c.get('max_abs_error', 0.) for c in cases),
                              'execution_s': record['execution_s']}), flush=True)
            assert record['passed']
    finally:
        shutil.rmtree(work)
assert len(comparisons) == 6
print(json.dumps({'passed': True, 'profiles': 6, 'requests': 81, 'observed_feeds': 87,
                  'model_inference_accepted': False}), flush=True)
