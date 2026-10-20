"""One real raw projection feed per dtype; no public judge acceptance."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import numpy as np

area = Path('/app/.ken/rust-migration/m2-optional')
pre = area / 'preflight'
out = pre / 'judge-core-linux-viability'
out.mkdir(exist_ok=False)
profiles = sorted((pre / 'judge-original-full-v2').glob('torch-cpu-*.json'))
assert len(profiles) == 3
registration = json.loads(profiles[0].read_text())['capture']['model_registration']
source = area / 'sources' / registration['model_id'].replace('/', '--') / registration['revision']
work = Path(tempfile.mkdtemp(prefix='ken-owned-judge-core-', dir='/tmp'))
comparisons = []
try:
    (work / 'lib').mkdir()
    (work / 'snapshot').mkdir()
    (work / 'sentinel-bin').mkdir()
    libraries = json.loads((area / 'libtorch-linux-2.9.0/PREPARATION.json').read_text())['libraries']
    for row in libraries:
        target = work / 'lib' / row['name']
        shutil.copy2(area / 'libtorch-linux-2.9.0/lib' / row['name'], target)
        assert target.stat().st_size == row['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest() == row['sha256']
    for name in ('config.json', 'model.safetensors'):
        target = work / 'snapshot' / name
        shutil.copy2(source / name, target)
        with target.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert sha == next(row['sha256'] for row in registration['files'] if row['path'] == name)
    binary = work / 'qwen-experiment'
    shutil.copy2(area / 'tensor-target-linux/release/qwen-experiment', binary)
    for profile in profiles:
        reference = json.loads(profile.read_text())['capture']
        expected = next(row for row in reference['results'] if row['id'] == 'purpose_tests')
        first, last = expected['feed_range']
        assert expected['passed_original_call'] and last == first + 1
        feed = reference['feeds'][first]
        request = {'dtype': feed['weight_dtype'].removeprefix('torch.'), 'device': 'cpu',
                   'input_ids': feed['inputs']['input_ids'], 'attention_mask': feed['inputs']['attention_mask'],
                   'projection_ids': feed['projection_ids'], 'include_hidden': False}
        path = work / 'requests.json'
        path.write_text(json.dumps({'cases': [request]}) + '\n')
        target = out / profile.stem
        target.mkdir()
        shutil.copy2(path, target / 'requests.json')
        trace = work / 'exec.trace'
        env = {'PATH': str(work / 'sentinel-bin'), 'HOME': str(work), 'TMPDIR': str(work),
               'LD_LIBRARY_PATH': str(work / 'lib'), 'LD_DEBUG': 'libs', 'OMP_NUM_THREADS': '2'}
        process = subprocess.Popen(['/usr/bin/strace', '-f', '-e', 'trace=process', '-o', str(trace),
                                    str(binary), str(work / 'snapshot'), str(path)], cwd=work, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
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
        (target / 'native.loader.log').write_bytes(stderr)
        shutil.copy2(trace, target / 'native.exec.trace')
        assert process.returncode == 0, (profile.name, process.returncode, stderr[-4000:])
        native = json.loads(stdout)
        assert len(native['cases']) == 1 and native['model_inference_accepted'] is False
        assert native['cases'][0]['repeat_exact'] and native['cases'][0]['hidden_f32'] is None
        actual = np.asarray(native['cases'][0]['scores_f32'], dtype=np.float32)
        wanted = np.frombuffer(bytes.fromhex(expected['scores_f32le_hex']), dtype='<f4')
        assert actual.shape == wanted.shape and np.isfinite(actual).all()
        error = float(np.max(np.abs(actual - wanted)))
        loaded = re.findall(r'calling init: (/.+)', stderr.decode())
        assert loaded and str(work / 'lib/libtorch_cpu.so') in loaded
        assert all(path.startswith(('/lib/', '/usr/lib/', str(work / 'lib') + '/')) for path in loaded)
        assert not any('python' in path.lower() for path in loaded)
        execs = re.findall(r'\bexecve\("([^"]+)"', trace.read_text())
        assert execs == [str(binary)]
        row = {'profile': profile.name, 'case': 'purpose_tests', 'passed': error <= 1e-5,
               'max_abs_error': error, 'fixed_tolerance': 1e-5, 'loaded_libraries': loaded,
               'libraries': libraries, 'exec_attempts': execs, 'outside_checkout': True,
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'original_sha256': hashlib.sha256(profile.read_bytes()).hexdigest(),
               'model_inference_accepted': False, 'scope': 'One observed real raw-score feed per dtype; dependency feasibility only.'}
        comparisons.append(row)
        (target / 'comparison.json').write_text(json.dumps(row, indent=2) + '\n')
        assert row['passed']
        print(json.dumps({'profile': profile.name, 'passed': True, 'max_abs_error': error}), flush=True)
finally:
    shutil.rmtree(work)
receipt = {'passed': True, 'profiles': comparisons, 'model_inference_accepted': False}
(out / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'passed': True, 'profiles': 3, 'model_inference_accepted': False}), flush=True)
