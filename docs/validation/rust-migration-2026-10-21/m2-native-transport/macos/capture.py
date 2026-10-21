"""Observe actual public+offline native acquisition outside the checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
parser.add_argument('--probe', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
repo, probe, out = args.repo.resolve(), args.probe.resolve(), args.out.resolve()
sys.path.insert(0, str(repo))
from tools.rust_migration.transformer_evidence import source_identity

def identity(path):
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}

assert not out.exists()
source = source_identity(repo)
model = json.loads((repo/'crates/ken-models/resources/transformer-catalog.json').read_bytes())['models'][0]
asset = model['assets'] | {'artifacts': {'config.json': model['assets']['artifacts']['config.json']}}
expected = asset['artifacts']['config.json']
out.mkdir(parents=True)
registration = out/'assets.json'
registration.write_text(json.dumps(asset, indent=2)+'\n')
system = 'macos' if platform.system() == 'Darwin' else 'linux'
results = []
with tempfile.TemporaryDirectory(prefix='ken-native-acquisition-') as temporary:
    work = Path(temporary)
    assert not work.is_relative_to(repo)
    binary = work/'native-acquisition'
    shutil.copy2(probe, binary)
    assert identity(binary) == identity(probe)
    assert binary.read_bytes()[:4] in (b'\x7fELF', b'\xcf\xfa\xed\xfe')
    sentinels = work/'sentinels'
    sentinels.mkdir()
    for name in ('python', 'python3', 'ken', 'sh', 'bash', 'zsh'):
        path = sentinels/name
        path.write_text('#!/bin/sh\nexit 97\n')
        path.chmod(0o755)
    environment = {'PATH': str(sentinels), 'HOME': str(work), 'HF_TOKEN': 'never-send-test-token',
                   'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9',
                   'ALL_PROXY': 'http://127.0.0.1:9'}
    environment['DYLD_PRINT_LIBRARIES' if system == 'macos' else 'LD_DEBUG'] = '1' if system == 'macos' else 'libs'
    for policy in ('public', 'offline'):
        command = [str(binary), str(registration), str(out/'cache'), policy]
        if system == 'linux':
            tracer = shutil.which('strace')
            assert tracer
            command = [tracer, '-f', '-e', 'trace=execve,execveat,connect', '-o', str(out/(policy+'.trace')), *command]
        with (out/(policy+'.stdout')).open('wb') as stdout, (out/(policy+'.stderr')).open('wb') as stderr:
            process = subprocess.Popen(command, cwd=work, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                code = process.wait(timeout=120)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        assert code == 0, (out/(policy+'.stderr')).read_text()[-3000:]
        raw = (out/(policy+'.stdout')).read_text()
        assert len(raw.splitlines()) == 1
        frame = json.loads(raw)
        assert frame['operation'] == 'acquire' and frame['policy'] == policy
        assert frame['transport_open_calls'] == (1 if policy == 'public' else 0)
        resolved = Path(frame['resolved'])
        assert resolved.is_relative_to(out/'cache/models') and resolved.name == asset['revision']
        assert identity(resolved/'config.json') == expected
        loader = (out/(policy+'.stderr')).read_text()
        assert 'libpython' not in loader and 'libtorch_python' not in loader
        trace = None
        if system == 'linux':
            trace = (out/(policy+'.trace')).read_text()
            assert len(re.findall(r'\bexecve(?:at)?\(', trace)) == 1
            assert policy != 'offline' or 'connect(' not in trace
        results.append({'policy': policy, 'command': command, 'native_exit': code,
                        'frame': frame, 'actual_artifact': identity(resolved/'config.json'),
                        'outside_checkout': True, 'exec_attempts': 1 if trace is not None else None,
                        'both_exec_syscalls_observed': system == 'linux',
                        'offline_connect_attempts': 0 if trace is not None and policy == 'offline' else None})
    (out/'dependencies.log').write_bytes(subprocess.check_output(
        ['/usr/bin/otool', '-L', str(binary)] if system == 'macos' else ['ldd', str(binary)]))
assert source_identity(repo) == source
summary = {'format': 'ken-native-public-acquisition/1', 'passed': True, 'M2_accepted': False,
           'new_neural_execution_claimed': False, 'platform': system,
           'source_files': source, 'probe': identity(probe), 'asset': asset,
           'url': f'https://huggingface.co/{asset["model_id"]}/resolve/{asset["revision"]}/config.json',
           'results': results}
(out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps({'passed': True, 'platform': system, 'actual_bytes': expected['bytes'],
                  'public_downloads': 1, 'offline_transport_calls': 0, 'M2_accepted': False}))
