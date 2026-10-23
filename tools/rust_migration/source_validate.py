"""Native source traversal experiments and independent saved-observation replay."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile


def definitions_digest(definitions: list[dict]) -> str:
    return hashlib.sha256(json.dumps(definitions, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def source_identity(repo: Path) -> dict:
    files = [repo / p for p in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'crates/ken-core/Cargo.toml')]
    files += sorted((repo / 'crates/ken-core/src').rglob('*.rs'))
    files.append(repo / 'crates/ken-core/examples/source_probe.rs')
    return {str(p.relative_to(repo)): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(files)}


def compare_source_observations(reference: dict, actual: dict, sources: dict,
                                native_sha256: str) -> list[str]:
    """Expected membership comes only from the separately captured original."""
    try:
        def require(condition, message):
            if not condition:
                raise ValueError(message)
        require(actual['format'] == 'ken-source-execution/1', 'wrong native protocol')
        require(actual['sources'] == sources, 'native source identity differs')
        require(actual['native_sha256'] == native_sha256, 'actual native host identity differs')
        require(actual['definitions_sha256'] == definitions_digest(reference['definitions']), 'original rule/tree inputs differ')
        expected = [(case['id'], index, walk) for case in reference['cases']
                    for index, walk in enumerate(case['walks'])]
        require(len(actual['observations']) == len(expected), 'missing or duplicated source observation')
        for row, (case, index, walk) in zip(actual['observations'], expected, strict=True):
            require((row['case'], row['scope_index']) == (case, index), 'source case inventory/order differs')
            request = row['request']; result = row['actual']
            require(set(request) == {'root', 'scope'} and Path(request['root']).is_absolute()
                    and request['scope'] == walk['scope'], 'actual source request differs')
            require(result['format'] == 'ken-source-observation/1' and result['scope'] == walk['scope'], 'wrong observed scope')
            if 'error' in walk:
                require(walk['error']['type'] == 'ValueError' and 'escapes project root' in walk['error']['message'],
                        'unsupported original error cannot become a declared correction')
                require(result['entries'] == [] and result['errors'] == [
                    {'kind': 'outside_project', 'path': walk['scope']}], 'original scope rejection differs')
            else:
                require(result['errors'] == [] and result['entries'] == walk['entries'], 'original ordered membership/types differ')
                require([r['path'] for r in result['entries'] if r['is_dir'] is False] == walk['files'], 'original file membership differs')
                require(all(type(r['is_dir']) is bool for r in result['entries']), 'directory type must be a Boolean')
        return []
    except (ValueError, KeyError, TypeError, IndexError) as error:
        return [str(error)]


def _populate(root: Path, definition: dict) -> None:
    for field in ('files', 'byte_files'):
        for name, content in definition.get(field, {}).items():
            path = root / name
            if path.is_absolute() and not path.is_relative_to(root) or '..' in Path(name).parts:
                raise ValueError('relative fixture identity required')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode() if field == 'files' else bytes.fromhex(content))
    for name, target in definition.get('links', {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)


def run_native_walk(probe: Path, request: dict, out: Path, sandbox: Path) -> dict:
    """Execute the copied native consumer with no Python/Git on PATH."""
    out.mkdir(parents=True)
    (out / 'inputs.json').write_text(json.dumps(request, indent=2) + '\n')
    command = [str(probe)]
    trace = out / 'exec.trace'
    if platform.system() == 'Linux':
        tracer = shutil.which('strace')
        if tracer is None:
            raise RuntimeError('actual Linux execution audit requires strace')
        command = [tracer, '--seccomp-bpf', '-f', '-e', 'trace=execve,execveat,connect', '-o', str(trace), *command]
    env = {'PATH': str(sandbox / 'empty-path'), 'HOME': str(sandbox / 'home'),
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    env['DYLD_PRINT_LIBRARIES' if platform.system() == 'Darwin' else 'LD_DEBUG'] = '1' if platform.system() == 'Darwin' else 'libs'
    execution = subprocess.run(command, input=json.dumps(request).encode(), capture_output=True,
                               cwd=sandbox, env=env, timeout=15, check=False)
    (out / 'stdout.json').write_bytes(execution.stdout)
    (out / 'stderr.log').write_bytes(execution.stderr)
    receipt = dict(command=command, exit=execution.returncode,
                   native_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
                   cwd=str(sandbox), env=env, timeout_s=15)
    (out / 'execution.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if execution.returncode or len(execution.stdout) > 8 * 1024 * 1024:
        raise ValueError('native source observation failed: ' + execution.stderr[-3000:].decode(errors='replace'))
    if b'libpython' in execution.stderr or b'libtorch_python' in execution.stderr:
        raise ValueError('Python native dependency is forbidden')
    if platform.system() == 'Linux':
        audit = trace.read_text()
        if len(re.findall(r'\bexecve(?:at)?\(', audit)) != 1 or re.search(r'\bconnect\(', audit):
            raise ValueError('source probe executed another program or opened a connection')
    return json.loads(execution.stdout)


def capture_native_sources(probe: Path, reference: dict, repo: Path, out: Path) -> dict:
    before = source_identity(repo)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='ken-source-process-') as directory:
        sandbox = Path(directory).resolve()
        (sandbox / 'empty-path').mkdir(); (sandbox / 'home').mkdir()
        native = sandbox / 'source-probe'; shutil.copy2(probe, native)
        observations = []
        for definition, expected in zip(reference['definitions'], reference['cases'], strict=True):
            project = sandbox / definition['id']; project.mkdir()
            _populate(project, definition)
            for index, walk in enumerate(expected['walks']):
                request = {'root': str(project), 'scope': walk['scope']}
                folder = out / 'observations' / definition['id'] / f'{index:02d}'
                actual = run_native_walk(native, request, folder, sandbox)
                observations.append(dict(case=definition['id'], scope_index=index, request=request, actual=actual))
        result = dict(format='ken-source-execution/1', sources=before,
                      native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),
                      definitions_sha256=definitions_digest(reference['definitions']), observations=observations)
        # These integrity corrections have their own inputs/expectations, never
        # substituted into the original compatibility histories above.
        project = sandbox / 'integrity'; project.mkdir(); (project / 'valid.py').write_text('valid')
        outside = sandbox / 'external'; outside.mkdir(); (outside / 'secret.py').write_text('private')
        (project / 'cycle').symlink_to('.')
        (project / 'external-dir').symlink_to(outside)
        (project / 'external-file').symlink_to(outside / 'secret.py')
        integrity = run_native_walk(native, {'root': str(project), 'scope': '.'}, out / 'integrity', sandbox)
        expected_integrity = {'format': 'ken-source-observation/1', 'scope': '.',
            'entries': [{'path': 'valid.py', 'is_dir': False}], 'errors': [
                {'kind': 'cycle', 'path': 'cycle'}, {'kind': 'outside_project', 'path': 'external-dir'},
                {'kind': 'outside_project', 'path': 'external-file'}]}
        if integrity != expected_integrity:
            raise ValueError('explicit native traversal integrity corrections differ')
        result['integrity'] = integrity
    if source_identity(repo) != before:
        raise ValueError('native source inputs changed during execution')
    errors = compare_source_observations(reference, result, before, result['native_sha256'])
    if errors:
        raise ValueError(errors)
    (out / 'observations.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    return result
