"""Compare real autonomous NPZ inference against its frozen Python contract."""
from __future__ import annotations

import argparse
import json
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
from .model_compare import _audit, _sha, _vector
from .reference import Reference
from .table_reference import TOLERANCES, capture

RUNTIME = {'engine': 'rust', 'ken_models': '0.18.0', 'tokenizers': '0.22.2',
           'npyz': '0.9.1', 'zip': '6.0.0', 'ndarray': '0.17.1', 'device': 'cpu'}
GOLDEN = Path(__file__).resolve().parents[2] / 'docs/validation/rust-migration-2026-10-18/m2-table/reference.json'


def compare_output(expected: dict, actual: object) -> list[str]:
    if not isinstance(actual, dict):
        return ['native output must be an object']
    errors = []
    for key in ('dimension', 'artifact', 'meta'):
        errors.extend(_differences(expected[key], actual.get(key), key))
    runtime = actual.get('runtime')
    if not isinstance(runtime, dict) or any(runtime.get(k) != v for k, v in RUNTIME.items()):
        errors.append('incorrect effective native runtime')
    received = actual.get('results')
    if not isinstance(received, list) or [r.get('id') if isinstance(r, dict) else None for r in received] != [c['id'] for c in expected['cases']]:
        return errors + ['missing, duplicated, reordered or unexpected case IDs']
    for case, wanted, result in zip(expected['cases'], expected['results'], received, strict=True):
        fields = ('load_ns', 'inference_ns', 'peak_after_load_bytes', 'peak_after_inference_bytes')
        if any(type(result.get(k)) is not int or result[k] <= 0 for k in fields):
            errors.append('missing phase measurements')
        elif result['peak_after_inference_bytes'] < result['peak_after_load_bytes']:
            errors.append('decreasing cumulative process peak')
        calls = result.get('calls')
        if not isinstance(calls, list) or len(calls) != len(case['calls']):
            errors.append('missing or extra calls'); continue
        for index, (call, want, got) in enumerate(zip(case['calls'], wanted['calls'], calls, strict=True)):
            path = f"{case['id']}.calls[{index}]"
            if call['op'] == 'tokens':
                if not isinstance(got, list) or any(type(v) is not int for v in got) or got != want:
                    errors.append(f'{path}: token IDs differ')
            elif call['op'] == 'count':
                if type(got) is not int or got != want:
                    errors.append(f'{path}: token count differs')
            elif call['op'] == 'query':
                errors.extend(_vector(want, got, expected['dimension'], TOLERANCES, path))
            elif call['op'] in ('passages', 'queries'):
                if not isinstance(got, list) or len(got) != len(want):
                    errors.append(f'{path}: row count differs'); continue
                for row, (a, b) in enumerate(zip(want, got, strict=True)):
                    errors.extend(_vector(a, b, expected['dimension'], TOLERANCES, f'{path}[{row}]'))
            else:
                errors.append(f'{path}: unknown operation')
    return errors


def compare(reference: Reference, native: Path, artifact: Path, out: Path) -> dict:
    out = out.resolve(); out.mkdir(parents=True, exist_ok=True)
    receipt = {'format': 'ken-table-parity/1', 'passed': False, 'errors': [],
               'platform': platform.system(), 'architecture': platform.machine(),
               'outside_checkout': False, 'native_children': [], 'M2_accepted': False}
    try:
        if not native.is_absolute() or not native.is_file() or not os.access(native, os.X_OK):
            raise ValueError('explicit built native table executable required')
        with native.open('rb') as stream:
            if stream.read(4) not in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
                raise ValueError('native executable required; interpreter scripts rejected')
        golden = json.loads(GOLDEN.read_text())
        if golden['tolerances'] != TOLERANCES or _sha(artifact) != golden['artifact']['sha256']:
            raise ValueError('fixed artifact or tolerances changed')
        receipt.update(case_ids=[c['id'] for c in golden['cases']], artifact=golden['artifact'],
                       cases_sha256=_sha(GOLDEN), native_sha256=_sha(native),
                       dependency_audit=_audit(native, out))
        if not receipt['dependency_audit']['passed']:
            raise ValueError('dependency audit failed')
        with tempfile.TemporaryDirectory(prefix='ken-table-process-') as directory:
            root = Path(directory)
            oracle_artifact = root / 'python.npz'; native_artifact = root / 'native.npz'
            for path in (oracle_artifact, native_artifact): shutil.copyfile(artifact, path)
            expected = capture(reference, oracle_artifact, out / 'oracle.json', cases=golden['cases'],
                               expected_sha256=golden['artifact']['sha256'])
            # A newly captured reference must still agree with the pre-port golden.
            frozen = dict(expected, runtime=RUNTIME)
            receipt['errors'].extend(compare_output(golden, frozen))
            if expected['oracle']['runtime'] != golden['oracle']['runtime']:
                raise ValueError('frozen Python runtime differs from declared oracle')
            copied = root / 'table-probe'; shutil.copy2(native, copied)
            shims = root / 'sentinel-path'; shims.mkdir(); child_log = root / 'children.log'
            for name in ('python', 'python3', 'ken', 'sh', 'bash', 'zsh'):
                shim = shims / name
                shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(child_log))}\nexit 97\n")
                shim.chmod(0o755)
            command = [str(copied)]
            if platform.system() == 'Linux':
                tracer = shutil.which('strace')
                if not tracer: raise ValueError('Linux requires actual strace')
                command = [tracer, '-f', '-e', 'trace=execve,execveat', '-o', str(out / 'native-exec.trace'), *command]
            started = time.monotonic_ns()
            process = subprocess.run(command, cwd=root,
                env={'PATH': str(shims), 'HOME': str(root), 'TOKENIZERS_PARALLELISM': 'false'},
                input=json.dumps({'artifact': str(native_artifact), 'cases': golden['cases']}),
                text=True, capture_output=True, timeout=240)
            receipt.update(native_wall_ns=time.monotonic_ns()-started, native_exit=process.returncode,
                outside_checkout=True, native_children=child_log.read_text().splitlines() if child_log.exists() else [])
            (out / 'native.stdout.json').write_text(process.stdout)
            (out / 'native.stderr.log').write_text(process.stderr)
            if process.returncode or process.stderr or receipt['native_children']:
                raise ValueError('native process failed or executed forbidden children')
            actual = json.loads(process.stdout)
            receipt['errors'].extend(compare_output(expected, actual))
            if platform.system() == 'Linux':
                lines = [line for line in (out / 'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(', line)]
                receipt['exec_attempts'] = len(lines)
                if len(lines) != 1 or str(copied) not in lines[0]:
                    receipt['errors'].append('only initial exec may occur')
            for path in (oracle_artifact, native_artifact, artifact):
                if _sha(path) != golden['artifact']['sha256']:
                    receipt['errors'].append('artifact changed during comparison')
            if _sha(copied) != receipt['native_sha256'] or _sha(native) != receipt['native_sha256']:
                receipt['errors'].append('native executable changed')
            if isinstance(actual, dict): receipt['runtime'] = actual.get('runtime')
            receipt['reference_runtime'] = expected['oracle']['runtime']
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed'] = not receipt['errors']
    (out / 'summary.json').write_text(json.dumps(receipt, indent=2, allow_nan=False)+'\n')
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(Reference.load(args.reference), args.native, args.artifact, args.out)
    print(json.dumps({'passed': result['passed'], 'errors': result['errors']}))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
