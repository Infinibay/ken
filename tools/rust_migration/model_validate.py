"""Accept one native model profile only after matching Linux and macOS gates."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import statistics

from .model_compare import compare_models
from .model_reference import TOLERANCES, model_cases
from .receipts import compare_python
from .reference import Reference, reference_env
from .validate import _command, _digest, _fingerprints, _rustc_version, _sha, _typing_errors, _verify, _write, bind_native_release
from .preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation,TRANSLATION_BUILD_ENV,context_environment,ettin_environment,translation_environment

REQUIRED_GATES = ('originals', 'reference', 'toolchain', 'python_contracts', 'python_full', 'typing',
                  'fmt', 'clippy', 'rust_tests', 'release', 'parity_tests', 'model_parity',
                  'm1_parity', 'autonomy', 'benchmark', 'hygiene')
FINGERPRINT_KEYS = {'native_source', 'reference_source', 'cases', 'validator', 'oracle', 'registration'}


def aggregate_models(directory: Path, *, expected_ids: list[str] | None = None) -> dict:
    errors, rows = [], []
    expected_ids = [c['id'] for c in model_cases()] if expected_ids is None else expected_ids
    for path in sorted(directory.rglob('summary.json')):
        try:
            row = json.loads(path.read_text())
            if isinstance(row, dict) and row.get('scope') == 'model-local':
                rows.append(row)
        except (OSError, ValueError):
            errors.append(f'unreadable model receipt: {path.name}')
    if sorted(row.get('platform', '') for row in rows) != ['Darwin', 'Linux']:
        errors.append('exactly one Linux and one macOS receipt required')
    signatures = []
    for row in rows:
        name = row.get('platform')
        gates = row.get('gates', {})
        if (row.get('passed') is not True or row.get('execution_error') or row.get('M2_accepted') is not False
                or any(not isinstance(gates.get(g), dict) or gates[g].get('ran') is not True
                       or gates[g].get('passed') is not True for g in REQUIRED_GATES)):
            errors.append(f'incomplete model gates: {name}')
        identities = row.get('fingerprints', {})
        if set(identities) != FINGERPRINT_KEYS or any(not isinstance(v, str) or len(v) != 64
                or any(c not in '0123456789abcdef' for c in v) for v in identities.values()):
            errors.append(f'incomplete source identities: {name}')
        signatures.append((identities, row.get('rustc')))
        if not str(row.get('rustc', '')).startswith('rustc 1.95.0 '):
            errors.append(f'wrong toolchain: {name}')
        if row.get('case_ids') != expected_ids:
            errors.append(f'missing, reordered or unexpected model cases: {name}')
        parity = row.get('model_parity', {})
        if (parity.get('passed') is not True or parity.get('outside_checkout') is not True
                or parity.get('native_children') != [] or parity.get('dependency_audit', {}).get('passed') is not True):
            errors.append(f'missing native process proof: {name}')
        if name == 'Linux' and parity.get('exec_attempts') != 1:
            errors.append('Linux must trace exactly one initial exec')
    if signatures and any(s != signatures[0] for s in signatures):
        errors.append('platform sources, oracle, artifacts, cases or compiler differ')
    passed = not errors and len(rows) == 2
    return {'scope': 'model-matrix', 'passed': passed, 'errors': errors,
            'platforms': [r.get('platform') for r in rows], 'Potion_accepted': passed, 'M2_accepted': False}


def assess_model_samples(samples: list[dict]) -> dict:
    errors, metrics = [], {}
    fields = ['load_ns', 'inference_ns', 'peak_after_load_bytes', 'peak_after_inference_bytes']
    expected = {(e, s) for e in ['python', 'native'] for s in ['query', 'passages']}
    if any((s.get('engine'), s.get('scenario')) not in expected for s in samples):
        errors.append('unexpected sample group')
    for engine, scenario in sorted(expected):
        group = [s for s in samples if (s.get('engine'), s.get('scenario')) == (engine, scenario)]
        if (len(group) != 30 or sorted(s.get('index', -1) for s in group) != list(range(30))
                or any(type(s.get(k)) is not int or s[k] <= 0 for s in group for k in fields)
                or any(s['peak_after_inference_bytes'] < s['peak_after_load_bytes'] for s in group)):
            errors.append(f'incomplete or invalid model samples: {engine}/{scenario}'); continue
        metrics[f'{engine}/{scenario}'] = {k: {'median': statistics.median(s[k] for s in group),
            'p95': sorted(s[k] for s in group)[math.ceil(.95*len(group))-1], 'max': max(s[k] for s in group)} for k in fields}
    return {'passed': not errors, 'errors': errors, 'metrics': metrics, 'samples': samples}


def _model_fingerprints(repo: Path, reference: Reference|None, cases: Path) -> dict:
    result = _fingerprints(repo, reference, cases)
    files = [repo / n for n in ['Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml']]
    files += sorted(p for p in (repo / 'crates').rglob('*') if p.is_file())
    result['native_source'] = _digest([{'path': p.relative_to(repo).as_posix(), 'sha256': _sha(p)} for p in files])
    result['oracle'] = _sha(cases.parent / 'potion-reference.json')
    result['registration'] = _sha((reference.root if reference is not None else repo) / 'src/ken/embedder/data/potion-code-16M-v2.json')
    return result


def benchmark_model(reference: Reference, native: Path, snapshot: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for i in range(30):
        # Alternate scenarios so load order does not group one workload first.
        order = ['query', 'passages'] if i % 2 == 0 else ['passages', 'query']
        for scenario in order:
            call = {'op': 'query', 'text': 'alpha beta'} if scenario == 'query' else {
                'op': 'passages', 'texts': ['def save_config(path): return read_json(path)',
                                           '¿Dónde se guarda la configuración?'] * 32}
            cases.append({'id': f'{scenario}:{i}', 'calls': [call]})
    case_path = output / 'cases.json'; _write(case_path, {'cases': cases, 'tolerances': TOLERANCES})
    parity = compare_models(reference, native, snapshot, case_path, output / 'processes')
    samples = []
    if parity['passed']:
        for engine, filename in [('python', 'oracle.json'), ('native', 'native.stdout.json')]:
            result = json.loads((output / 'processes' / filename).read_text())
            for row in result['results']:
                scenario, index = row['id'].split(':')
                samples.append({'engine': engine, 'scenario': scenario, 'index': int(index),
                    **{key: row.get(key) for key in ['load_ns', 'inference_ns', 'peak_after_load_bytes', 'peak_after_inference_bytes']}})
    report = assess_model_samples(samples)
    report['passed'] = report['passed'] and parity['passed']
    report.update(process_parity=parity['passed'],
        method='30 fresh encoder loads per workload inside one process per engine; ordered calls, no samples discarded',
        memory='post-exec process peak measured after each phase; Linux /proc/self/status VmHWM, macOS self getrusage; cumulative across loads, not isolated model allocations',
        timing='model construction and inference measured separately; Python construction also re-verifies registered files, Rust consumes previously verified owned bytes',
        native_preparation_ns=json.loads((output / 'processes/native.stdout.json').read_text()).get('prepare_ns') if parity['passed'] else None)
    _write(output / 'benchmark.json', report)
    return report


def validate_models(repo: Path, reference: Reference, native: Path, snapshot: Path, output: Path,
                    baseline_dir: Path, original_manifest: Path, *, table_probe: Path | None = None,
                    context:PreparedNativeContext|None=None,ettin:PreparedNativeEttin|None=None,translation:PreparedNativeTranslation|None=None) -> int:
    repo, output, native, snapshot = repo.resolve(), output.resolve(), native.resolve(), snapshot.absolute()
    output.mkdir(parents=True, exist_ok=True)
    gates = {}
    result = {'scope': 'model-local', 'platform': platform.system(), 'architecture': platform.machine(),
              'passed': False, 'M2_accepted': False, 'gates': gates}
    _write(output / 'summary.json', result)
    cases = repo / 'docs/validation/rust-migration-2026-10-18/m2-static/cases.json'
    def finish():
        result['errors'] = (['execution_error'] if result.get('execution_error') else []) + [g for g in REQUIRED_GATES
            if gates.get(g, {}).get('ran') is not True or gates[g].get('passed') is not True]
        result['passed'] = not result['errors']; result['Potion_local_accepted'] = result['passed']
        _write(output / 'summary.json', result)
        return int(not result['passed'])
    gates['originals'] = _verify(repo, original_manifest)
    gates['reference'] = _verify(reference.root, reference.manifest_path)
    if not gates['originals']['passed'] or not gates['reference']['passed']:
        return finish()
    try:
        before = _model_fingerprints(repo, reference, cases); result['fingerprints'] = before
        env = reference_env(reference, output / 'environment')
        env.update(PYTHONPATH=os.pathsep.join([str(repo / 'src'), str(repo)]),
            KEN_RUST_REFERENCE=str(reference.root), KEN_RUST_BIN=str(repo / 'target/release/ken-rs'),
            KEN_MODEL_PROBE=str(native), KEN_POTION_SNAPSHOT=str(snapshot),
            KEN_TABLE_PROBE=str((table_probe or repo / 'target/release/examples/table_probe').resolve()),
            RUSTUP_HOME=os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup')),
            CARGO_HOME=os.environ.get('CARGO_HOME', str(Path.home() / '.cargo')))
        env.pop('CARGO_TARGET_DIR', None); env.pop('CARGO_BUILD_TARGET', None)
        env.update(context_environment(context))
        env.update(ettin_environment(ettin))
        for key in TRANSLATION_BUILD_ENV:env.pop(key,None)
        env.update(translation_environment(translation))
        py = [str(reference.python), '-m']
        gates['toolchain'] = _command(repo, env, output, 'rustc', ['rustc', '--version', '--verbose'])
        result['rustc'] = _rustc_version(output / 'rustc.log')
        gates['toolchain']['passed'] = gates['toolchain']['passed'] and result['rustc'].startswith('rustc 1.95.0 ')
        gates['python_contracts'] = _command(repo, env, output, 'python-contracts', [*py, 'pytest', 'tests/rust_migration', 'tests/test_paths.py', 'tests/test_status.py', '-q'])
        final = output / 'python-final.xml'
        gates['python_full'] = _command(repo, env, output, 'python-full', [*py, 'pytest', f'--junitxml={final}'], 3600)
        known = json.loads((repo / 'docs/validation/rust-migration-2026-10-18/m0/baseline-results.json').read_text()).get('diagnostic_rerun', {}).get('original_failures', [])
        comparison = compare_python(baseline_dir / 'python-baseline.xml', final, known)
        gates['python_full'].update(passed=gates['python_full'].get('exit') in (0, 1) and comparison['passed'], details=comparison)
        gates['typing'] = _command(repo, env, output, 'typing', [*py, 'mypy', '--no-incremental'])
        previous = _typing_errors(baseline_dir / 'mypy-baseline.log'); current = _typing_errors(output / 'typing.log')
        gates['typing'].update(passed=gates['typing'].get('exit') in (0,1) and not (current-previous)
            and (bool(current) or gates['typing'].get('exit') == 0), details={'previous_errors': sorted(previous), 'current_errors': sorted(current), 'new_errors': sorted(current-previous)})
        for name, command in [('fmt', ['cargo','fmt','--all','--','--check']),
                ('clippy', ['cargo','clippy','--locked','--workspace','--all-targets','--','-D','warnings']),
                ('rust_tests', ['cargo','test','--locked','--workspace']),
                ('release', ['cargo','build','--release','--locked','-p','ken-cli','-p','ken-models','--examples','--bins','--message-format=json'])]:
            gates[name] = _command(repo, env, output, name, command)
        rust_log = (output / 'rust_tests.log').read_text()
        import re
        ignored = re.findall(r'; (\d+) ignored;', rust_log)
        gates['rust_tests']['passed'] = gates['rust_tests']['passed'] and bool(ignored) and all(int(n) == 0 for n in ignored)
        binding=bind_native_release(repo,native,'model_probe')
        gates['release'].update(passed=gates['release']['passed'] and binding['passed'],native_binding=binding)
        gates['parity_tests'] = _command(repo, env, output, 'parity-tests', [*py,'pytest','migration_tests','-q',f'--junitxml={output / "parity-tests.xml"}'])
        parity = compare_models(reference, native, snapshot, cases, output / 'model-parity')
        result['model_parity'] = parity; result['case_ids'] = parity.get('case_ids', [])
        gates['model_parity'] = {'ran': True, 'passed': parity['passed'] and result['case_ids'] == [c['id'] for c in model_cases()]}
        gates['autonomy'] = {'ran': True, 'passed': parity['passed'] and parity['outside_checkout'] and parity['native_children'] == []
            and parity['dependency_audit']['passed'] and (platform.system() != 'Linux' or parity.get('exec_attempts') == 1)}
        gates['m1_parity'] = _command(repo, env, output, 'm1-parity', [*py,'tools.rust_migration.compare','--reference',str(reference.root),
            '--native',str(repo / 'target/release/ken-rs'),'--cases',str(repo / 'docs/validation/rust-migration-2026-10-18/m0/m1-cases.json'),
            '--out',str(output / 'm1-parity.json')])
        bench = benchmark_model(reference, native, snapshot, output / 'benchmark')
        gates['benchmark'] = {'ran': True, 'passed': bench['passed'], 'artifact': 'benchmark/benchmark.json'}
        gates['hygiene'] = _command(repo, env, output, 'hygiene', ['git','diff','--check'])
        gates['hygiene']['passed'] = gates['hygiene']['passed'] and before == _model_fingerprints(repo, reference, cases)
        gates['originals'] = _verify(repo, original_manifest); gates['reference'] = _verify(reference.root, reference.manifest_path)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result['execution_error'] = f'{type(error).__name__}: {error}'
    return finish()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=['local','matrix'], default='local')
    parser.add_argument('--platform-receipts', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--native', type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--original-manifest', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.scope == 'matrix':
        if not args.platform_receipts: parser.error('matrix requires --platform-receipts')
        result = aggregate_models(args.platform_receipts); _write(args.out / 'summary.json', result)
        return int(not result['passed'])
    if not all([args.reference, args.native, args.snapshot, args.baseline_dir, args.original_manifest]):
        parser.error('local requires reference, native, snapshot, baseline-dir and original-manifest')
    return validate_models(Path.cwd(), Reference.load(args.reference), args.native, args.snapshot,
                           args.out, args.baseline_dir, args.original_manifest)


if __name__ == '__main__':
    raise SystemExit(main())
