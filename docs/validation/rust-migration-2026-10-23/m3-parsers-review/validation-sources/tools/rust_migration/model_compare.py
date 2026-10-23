"""Strict process comparison for the fixed, registered native static encoder."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import time

from .compare import _differences
from .model_reference import TOLERANCES, capture
from .reference import Reference

RUNTIME = {'engine': 'rust', 'ken_models': '0.18.0', 'tokenizers': '0.22.2',
           'safetensors': '0.8.0', 'half': '2.7.1', 'device': 'cpu'}


def _vector(expected, actual, dimension, tolerance, path):
    if (not isinstance(actual, list) or len(actual) != dimension or len(expected) != dimension
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in actual)):
        return [f'{path}: invalid dimension or nonfinite/nonnumeric vector']
    if all(v == 0 for v in expected):
        return [] if all(v == 0 for v in actual) else [f'{path}: zero vector changed']
    errors = []
    if any(abs(a-b) > tolerance['atol'] + tolerance['rtol'] * abs(b) for a, b in zip(actual, expected)):
        errors.append(f'{path}: component tolerance exceeded')
    norm_a = math.sqrt(sum(a*a for a in actual)); norm_b = math.sqrt(sum(b*b for b in expected))
    if not norm_a or sum(a*b for a, b in zip(actual, expected)) / (norm_a*norm_b) < tolerance['cosine_min']:
        errors.append(f'{path}: cosine tolerance exceeded')
    return errors


def compare_output(expected: dict, actual: object) -> list[str]:
    """Check exact histories and identities before bounded numeric comparison."""
    if not isinstance(actual, dict):
        return ['native model output must be an object']
    errors = []
    for key in ['dimension', 'assets_fingerprint']:
        errors.extend(_differences(expected[key], actual.get(key), key))
    errors.extend(_differences(expected['identity'], actual.get('compatible_identity'), 'compatible_identity'))
    runtime = actual.get('runtime')
    if not isinstance(runtime, dict) or any(runtime.get(k) != v for k, v in RUNTIME.items()):
        errors.append('effective native runtime missing or incorrect')
    tolerance = TOLERANCES[expected['identity'].get('dtype', 'float32')]
    cases, wanted, received = expected['cases'], expected['results'], actual.get('results')
    if not isinstance(received, list) or [v.get('id') if isinstance(v, dict) else None for v in received] != [c['id'] for c in cases]:
        return errors + ['case IDs missing, duplicated, reordered or unexpected']
    for case, want, result in zip(cases, wanted, received, strict=True):
        values = result.get('calls')
        if not isinstance(values, list) or len(values) != len(case['calls']):
            errors.append(f"{case['id']}: missing or extra calls"); continue
        for index, (call, expected_value, value) in enumerate(zip(case['calls'], want['calls'], values, strict=True)):
            path = f"{case['id']}.calls[{index}]"
            if call['op'] == 'tokens':
                if not isinstance(value, list) or any(type(v) is not int for v in value) or value != expected_value:
                    errors.append(f'{path}: exact token IDs differ')
            elif call['op'] == 'count':
                if type(value) is not int or value != expected_value:
                    errors.append(f'{path}: exact token count differs')
            elif call['op'] == 'query':
                errors.extend(_vector(expected_value, value, expected['dimension'], tolerance, path))
            elif call['op'] == 'passages':
                if not isinstance(value, list) or len(value) != len(expected_value['rows']):
                    errors.append(f'{path}: passage row count differs'); continue
                for row, (actual_row, wanted_index) in enumerate(zip(value, expected_value['rows'], strict=True)):
                    errors.extend(_vector(expected_value['vectors'][wanted_index], actual_row,
                                          expected['dimension'], tolerance, f'{path}[{row}]'))
            else:
                errors.append(f'{path}: unknown operation')
    return errors


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit(probe: Path, output: Path,*,package:str='ken-models') -> dict:
    command = ['otool', '-L', str(probe)] if platform.system() == 'Darwin' else ['ldd', str(probe)]
    linked = subprocess.run(command, text=True, capture_output=True, timeout=30)
    repo = Path(__file__).resolve().parents[2]
    tree = subprocess.run(['cargo', 'tree', '--locked', '-p', package, '-e', 'normal'],
                          cwd=repo, text=True, capture_output=True, timeout=60)
    (output / 'dependencies.log').write_text(linked.stdout + linked.stderr)
    (output / 'cargo-tree.log').write_text(tree.stdout + tree.stderr)
    passed = linked.returncode == tree.returncode == 0 and not re.search(r'libpython|pyo3|cpython', linked.stdout + tree.stdout, re.I)
    return {'passed': passed, 'linked_exit': linked.returncode, 'tree_exit': tree.returncode,
            'linked_sha256': _sha(output / 'dependencies.log'), 'tree_sha256': _sha(output / 'cargo-tree.log')}


def compare_models(reference: Reference, native_probe: Path, snapshot: Path,
                   cases: Path, output: Path) -> dict:
    output = output.resolve(); output.mkdir(parents=True, exist_ok=True)
    receipt = {'format': 'ken-static-parity/1', 'passed': False, 'errors': [],
               'platform': platform.system(), 'architecture': platform.machine(),
               'native_children': [], 'outside_checkout': False, 'M2_accepted': False}
    (output / 'summary.json').write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        if not native_probe.is_absolute() or not native_probe.is_file() or not os.access(native_probe, os.X_OK):
            raise ValueError('explicit executable native probe required')
        with native_probe.open('rb') as stream:
            magic = stream.read(4)
        if magic not in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
            raise ValueError('probe must be a native executable, not an interpreter script')
        case_data = json.loads(cases.read_text())
        if case_data['tolerances'] != TOLERANCES:
            raise ValueError('predeclared tolerances changed')
        registration = json.loads((reference.root / 'src/ken/embedder/data/potion-code-16M-v2.json').read_text())
        receipt.update(case_ids=[c['id'] for c in case_data['cases']], cases_sha256=_sha(cases),
                       native_sha256=_sha(native_probe), dependency_audit=_audit(native_probe, output))
        if not receipt['dependency_audit']['passed']:
            raise ValueError('native dependency audit failed')
        with tempfile.TemporaryDirectory(prefix='ken-model-process-') as directory:
            root = Path(directory)
            # Each engine receives a separate verified copy; neither can change the other's inputs.
            snapshots = []
            for engine in ['python', 'native']:
                destination = root / engine / registration['revision']; destination.mkdir(parents=True)
                for name in registration['artifacts']:
                    target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(snapshot / name, target)
                snapshots.append(destination)
            expected = capture(reference, snapshots[0], output / 'oracle.json', cases=case_data['cases'])
            copied = root / 'model-probe'; shutil.copy2(native_probe, copied)
            shims = root / 'empty-runtime-path'; shims.mkdir()
            child_log = root / 'children.log'
            for name in ['python', 'python3', 'ken', 'sh', 'bash', 'zsh']:
                path = shims / name
                path.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(child_log))}\nexit 97\n")
                path.chmod(0o755)
            env = {'PATH': str(shims), 'HOME': str(root), 'TOKENIZERS_PARALLELISM': 'false'}
            request = {'registration': registration, 'snapshot': str(snapshots[1]),
                       'legacy_runtime': expected['oracle']['runtime'], 'cases': case_data['cases']}
            command = [str(copied)]
            if platform.system() == 'Linux':
                tracer = shutil.which('strace')
                if not tracer:
                    raise ValueError('strace is mandatory for Linux model acceptance')
                command = [tracer, '-f', '-e', 'trace=execve,execveat', '-o', str(output / 'native-exec.trace'), *command]
            started = time.monotonic_ns()
            native = subprocess.run(command, cwd=root, env=env, input=json.dumps(request), text=True,
                                    capture_output=True, timeout=180)
            receipt['native_wall_ns'] = time.monotonic_ns() - started
            (output / 'native.stdout.json').write_text(native.stdout)
            (output / 'native.stderr.log').write_text(native.stderr)
            receipt.update(outside_checkout=True, native_exit=native.returncode,
                           native_children=child_log.read_text().splitlines() if child_log.exists() else [])
            if native.returncode or native.stderr or receipt['native_children']:
                raise ValueError('native process failed, wrote stderr or executed forbidden children')
            actual = json.loads(native.stdout)
            receipt['errors'].extend(compare_output(expected, actual))
            if platform.system() == 'Linux':
                lines = [line for line in (output / 'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(', line)]
                receipt['exec_attempts'] = len(lines)
                if len(lines) != 1 or str(copied) not in lines[0]:
                    receipt['errors'].append('Linux trace requires only the initial exec')
            for index, destination in enumerate(snapshots):
                for name, record in registration['artifacts'].items():
                    if _sha(destination / name) != record['sha256']:
                        receipt['errors'].append(f'engine {index} changed registered artifact {name}')
            if _sha(copied) != receipt['native_sha256']:
                receipt['errors'].append('copied native probe changed during execution')
            receipt.update(assets_fingerprint=expected['assets_fingerprint'], compatible_identity=expected['identity'],
                           runtime=actual.get('runtime'), reference_runtime=expected['oracle']['runtime'])
        if _sha(native_probe) != receipt['native_sha256']:
            receipt['errors'].append('native probe source changed during execution')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed'] = not receipt['errors']
    (output / 'summary.json').write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=Path('docs/validation/rust-migration-2026-10-18/m2-static/cases.json'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare_models(Reference.load(args.reference), args.native, args.snapshot, args.cases, args.out)
    print(json.dumps({'passed': result['passed'], 'errors': result['errors']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
