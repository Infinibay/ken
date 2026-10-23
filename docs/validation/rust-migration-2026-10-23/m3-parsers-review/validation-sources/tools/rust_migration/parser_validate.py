"""Native parser input identity, complete comparisons and isolated execution."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
from .fastembed_process import _distinct, _nonfinite

LIMIT = 32 * 1024 * 1024

def identity(path: Path) -> dict:
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}

def load(path: Path):
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT: raise ValueError('parser evidence exceeds32MiB')
    return json.loads(raw, object_pairs_hook=_distinct, parse_constant=_nonfinite)

def source_identity(repo: Path) -> dict:
    paths = [repo / name for name in ('Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml')]
    paths += sorted(p for p in (repo / 'crates/ken-syntax').rglob('*') if p.is_file())
    return {str(p.relative_to(repo)): identity(p) for p in paths}

def case_id(request: dict) -> str:
    return hashlib.sha256(request['language'].encode() + b'\0' + request['hint'].encode() + b'\0' + bytes.fromhex(request['source_hex'])).hexdigest()

def parser_cases(repo: Path) -> list[dict]:
    folder = repo / 'crates/ken-syntax/tests/fixtures'
    cases = []
    for name in ('reference', 'parser-edges', 'c-macro-digits'):
        for original in load(folder / (name + '.json'))['cases']:
            row = {key: original[key] for key in ('input', 'parsed', 'syntax') if key in original}
            row['id'] = case_id(row['input']); cases.append(row)
    for row in load(folder / 'parser-errors.json')['cases']:
        request = dict(language=row['language'], hint='error.ts', source_hex=row['source_hex'])
        cases.append(dict(id=case_id(request), input=request, error=row['error']))
    if (folder / 'review-cases.json').is_file():
        for row in load(folder / 'review-cases.json')['cases']:
            cases.append(dict(id=case_id(row['input']), input=row['input'],
                **({'parsed': json.loads(row['parsed_json'])} if 'parsed_json' in row else {'error': row['error']})))
    if len(cases) != len({c['id'] for c in cases}): raise ValueError('duplicate original parser input')
    return cases

def compare_parser_observations(cases: list[dict], actual: dict) -> list[str]:
    try:
        if set(actual) != {'format', 'cases'} or actual['format'] != 'ken-parser-observation/1': raise ValueError('wrong parser observation protocol')
        if len(actual['cases']) != len(cases): raise ValueError('missing/duplicate parser cases')
        for expected, row in zip(cases, actual['cases'], strict=True):
            if row['id'] != expected['id']: raise ValueError('parser input identity/order differs')
            if 'error' in expected:
                if set(row) != {'id', 'error'} or expected['error']['type'] != 'UnicodeDecodeError' or 'utf-8' not in row['error']:
                    raise ValueError('original encoding failure differs')
            else:
                if set(row) != {'id', 'parsed', 'syntax'} or row['parsed'] != expected['parsed']: raise ValueError('complete ordered ParsedFile differs: ' + row['id'])
                if 'syntax' in expected and row['syntax'] != expected['syntax']: raise ValueError('complete syntax differs: ' + row['id'])
        return []
    except (ValueError, KeyError, TypeError) as error: return [str(error)]

def run_parser_capture(repo: Path, probe: Path, manifest: Path, cases: list[dict], out: Path) -> dict:
    """Prepare first, then run a copied executable and copied SDK outside checkout."""
    before = source_identity(repo); binary = identity(probe)
    if probe.read_bytes()[:4] not in (b'\x7fELF', b'\xcf\xfa\xed\xfe'): raise ValueError('native parser executable required')
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='ken-parser-process-') as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(repo.resolve()): raise ValueError('outside-checkout process required')
        native = root / 'parser-probe'; shutil.copy2(probe, native)
        sdk = root / 'sdk'; shutil.copytree(manifest.parent, sdk)
        prepared = load(sdk / manifest.name)
        resources = prepared['libraries']
        for row in resources:
            if identity(sdk / row['file']) != {k: row[k] for k in ('bytes', 'sha256')}: raise ValueError('prepared grammar differs')
        (root / 'empty-path').mkdir(); (root / 'home').mkdir()
        request = {'manifest': str(sdk / manifest.name), 'cases': [dict(id=c['id'], **c['input']) for c in cases]}
        env = {'PATH': str(root / 'empty-path'), 'HOME': str(root / 'home'), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
        system = 'macos' if platform.system() == 'Darwin' else 'linux'
        command = [str(native)]
        if system == 'linux':
            tracer = shutil.which('strace')
            if not tracer: raise ValueError('actual Linux exec/connect audit required')
            command = [tracer, '--seccomp-bpf', '-f', '-e', 'trace=execve,execveat,connect', '-o', str(out / 'exec.trace'), *command]
            env['LD_DEBUG'] = 'libs'
        else: env['DYLD_PRINT_LIBRARIES'] = '1'
        (out / 'inputs.json').write_text(json.dumps(request) + '\n')
        # Files cap resident capture memory; the fixed consumer also bounds its output.
        with (out / 'stdout.json').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
            result = subprocess.run(command, input=json.dumps(request).encode(), stdout=stdout, stderr=stderr, cwd=root, env=env, timeout=60, check=False)
        receipt = dict(format='ken-parser-execution/1', system=system, sources=before, native_sha256=binary['sha256'], resources=resources,
                       manifest=prepared, command=command, cwd=str(root), env=env, exit=result.returncode, timeout_s=60, case_count=len(cases))
        build = dict(sources=before, native_sha256=binary['sha256'], resources=resources, system=system)
        (out / 'BUILD.json').write_text(json.dumps(build, indent=2) + '\n')
        (out / 'execution.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if result.returncode: raise ValueError('native parser failed: ' + (out / 'stderr.log').read_text()[-2000:])
        if identity(native) != binary or identity(probe) != binary or source_identity(repo) != before: raise ValueError('native parser inputs changed during execution')
        for row in resources:
            if identity(sdk / row['file']) != {k: row[k] for k in ('bytes', 'sha256')}: raise ValueError('native grammar changed during execution')
    from .parser_evidence import verify_parser_capture
    errors = verify_parser_capture(out, cases)
    if errors: raise ValueError(errors)
    return receipt
