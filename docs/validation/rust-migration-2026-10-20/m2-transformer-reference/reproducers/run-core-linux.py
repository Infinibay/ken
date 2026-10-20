"""Native dependency-selection gate, not full public-adapter acceptance."""
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

area = Path('/app/.ken/rust-migration/m2-optional')
pre = area / 'preflight'
out = pre / 'core-linux-viability'
out.mkdir(exist_ok=False)
libraries = json.loads((area / 'libtorch-linux-2.9.0/PREPARATION.json').read_text())['libraries']
comparisons = []
for family, binary_name, weight_name in [('qwen', 'qwen-experiment', 'model.safetensors'),
                                          ('bge', 'xlmr-experiment', 'pytorch_model.bin')]:
    profiles = sorted((pre / 'st-original-full').glob(f'{family}-cpu-*.json'))
    assert len(profiles) == 3
    registration = json.loads(profiles[0].read_text())['model_registration']
    source = area / 'sources' / registration['model_id'].replace('/', '--') / registration['revision']
    work = Path(tempfile.mkdtemp(prefix=f'ken-owned-core-{family}-', dir='/tmp'))
    assert not work.is_relative_to(Path('/app'))
    try:
        (work / 'lib').mkdir()
        (work / 'snapshot').mkdir()
        (work / 'sentinel-bin').mkdir()
        children = work / 'children.log'
        for name in ('python', 'python3', 'python3.12', 'uv', 'pip'):
            sentinel = work / 'sentinel-bin' / name
            sentinel.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "' + str(children) + '"\nexit 97\n')
            sentinel.chmod(0o755)
        required = sum(row['bytes'] for row in registration['files'] if row['path'] in {weight_name, 'config.json'})
        required += sum(row['bytes'] for row in libraries) + 3 * 1024**3
        assert shutil.disk_usage(work).free >= required
        for row in libraries:
            target = work / 'lib' / row['name']
            shutil.copy2(area / 'libtorch-linux-2.9.0/lib' / row['name'], target)
            assert target.stat().st_size == row['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest() == row['sha256']
        for name in (weight_name, 'config.json'):
            row = next(row for row in registration['files'] if row['path'] == name)
            target = work / 'snapshot' / name
            shutil.copy2(source / name, target)
            with target.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            assert target.stat().st_size == row['bytes'] and digest == row['sha256']
        binary = work / binary_name
        shutil.copy2(area / 'tensor-target-linux/release' / binary_name, binary)
        for profile in profiles:
            reference = json.loads(profile.read_text())
            assert reference['package_versions']['torch'] == '2.9.0+cpu'
            selected = []
            for request, expected in zip(reference['requests'], reference['results'], strict=True):
                if request['id'] not in {'lexical', 'content_tokens_512'}:
                    continue
                assert expected['passed_original_call'] and expected['finite']
                first, last = expected['feed_range']
                assert last == first + 1
                selected.append((request, expected, reference['feeds'][first]))
            assert len(selected) == 2
            requests = [{'dtype': feed['weight_dtype'].removeprefix('torch.'), 'device': 'cpu',
                         'input_ids': feed['inputs']['input_ids'], 'attention_mask': feed['inputs']['attention_mask'],
                         'include_hidden': False} for _, _, feed in selected]
            requests_path = work / 'requests.json'
            requests_path.write_text(json.dumps({'cases': requests}) + '\n')
            target = out / profile.stem
            target.mkdir()
            shutil.copy2(requests_path, target / 'requests.json')
            trace = work / 'exec.trace'
            command = ['/usr/bin/strace', '-f', '-e', 'trace=process', '-o', str(trace),
                       str(binary), str(work / 'snapshot'), str(requests_path)]
            env = {'PATH': str(work / 'sentinel-bin'), 'HOME': str(work), 'TMPDIR': str(work),
                   'LD_LIBRARY_PATH': str(work / 'lib'), 'LD_DEBUG': 'libs', 'OMP_NUM_THREADS': '2'}
            start = time.monotonic()
            process = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=3600)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(0.5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(5)
            (target / 'native.stdout').write_bytes(stdout)
            (target / 'native.loader.log').write_bytes(stderr)
            shutil.copy2(trace, target / 'native.exec.trace')
            assert process.returncode == 0, (profile.name, process.returncode, stderr[-4000:])
            native = json.loads(stdout)
            assert native['model_inference_accepted'] is False and len(native['cases']) == 2
            assert all(row['repeat_exact'] and row['hidden_f32'] is None for row in native['cases'])
            loaded = re.findall(r'calling init: (/.+)', stderr.decode())
            assert loaded and str(work / 'lib/libtorch_cpu.so') in loaded
            assert all(path.startswith(('/lib/', '/usr/lib/', str(work / 'lib') + '/')) for path in loaded)
            assert not any('python' in path.lower() for path in loaded)
            execs = re.findall(r'\bexecve\("([^"]+)"', trace.read_text())
            assert execs == [str(binary)] and not children.exists()
            cases = []
            for (request, expected, _), actual in zip(selected, native['cases'], strict=True):
                values = np.asarray(actual['vectors_f32'], dtype=np.float32).reshape(expected['shape'])
                order = np.argsort([-len(text) for text in request['texts']])
                values = values[np.argsort(order)]
                wanted = np.frombuffer(bytes.fromhex(expected['vectors_f32le_hex']), dtype='<f4').reshape(expected['shape'])
                assert np.isfinite(values).all()
                error = float(np.max(np.abs(values - wanted)))
                cases.append({'id': request['id'], 'max_abs_error': error, 'fixed_tolerance': 1e-6, 'passed': error <= 1e-6})
            row = {'profile': profile.name, 'passed': all(case['passed'] for case in cases), 'cases': cases,
                   'execution_s': time.monotonic() - start, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                   'original_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(), 'loaded_libraries': loaded,
                   'exec_attempts': execs, 'native_children': [], 'outside_checkout': True,
                   'model_inference_accepted': False,
                   'scope': 'Two real observed feeds per model/dtype, lexical mixed-length and512token boundary; dependency feasibility only. Full production adapter corpus remains mandatory.'}
            (target / 'comparison.json').write_text(json.dumps(row, indent=2) + '\n')
            comparisons.append(row)
            (out / 'summary.json').write_text(json.dumps({'passed': all(row['passed'] for row in comparisons),
                'profiles': comparisons, 'model_inference_accepted': False}, indent=2) + '\n')
            print(json.dumps({'profile': profile.name, 'passed': row['passed'], 'cases': cases,
                              'execution_s': row['execution_s']}), flush=True)
            assert row['passed']
    finally:
        shutil.rmtree(work)
assert len(comparisons) == 6
print(json.dumps({'passed': True, 'profiles': 6, 'observed_batches': 12, 'model_inference_accepted': False}), flush=True)
