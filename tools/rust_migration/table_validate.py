"""Extend the complete native-model gates with the independent NPZ profile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform

from .model_validate import FINGERPRINT_KEYS, REQUIRED_GATES, _model_fingerprints, validate_models
from .reference import Reference
from .table_compare import GOLDEN, compare
from .table_reference import table_cases
from .validate import _sha, _write

TABLE_KEYS = FINGERPRINT_KEYS | {'table_artifact', 'table_oracle'}
TABLE_GATES = (*REQUIRED_GATES, 'table_parity')


def aggregate_tables(directory: Path, *, expected_ids: list[str] | None = None) -> dict:
    rows, errors = [], []
    expected_ids = [c['id'] for c in table_cases()] if expected_ids is None else expected_ids
    for path in sorted(directory.rglob('summary.json')):
        try:
            value = json.loads(path.read_text())
            if isinstance(value, dict) and value.get('scope') == 'table-local': rows.append(value)
        except (OSError, ValueError): errors.append(f'unreadable receipt: {path}')
    if sorted(row.get('platform', '') for row in rows) != ['Darwin', 'Linux']:
        errors.append('exactly one Linux and one macOS table receipt required')
    signatures = []
    for row in rows:
        name = row.get('platform'); gates = row.get('gates', {})
        if row.get('passed') is not True or row.get('execution_error') or row.get('M2_accepted') is not False:
            errors.append(f'failed table receipt: {name}')
        if any(not isinstance(gates.get(g), dict) or gates[g].get('ran') is not True
               or gates[g].get('passed') is not True for g in TABLE_GATES):
            errors.append(f'incomplete full gates: {name}')
        identities = row.get('fingerprints', {})
        if set(identities) != TABLE_KEYS or any(not isinstance(v, str) or len(v) != 64
                or any(c not in '0123456789abcdef' for c in v) for v in identities.values()):
            errors.append(f'incomplete identities: {name}')
        signatures.append((identities, row.get('rustc')))
        if not str(row.get('rustc', '')).startswith('rustc 1.95.0 '): errors.append(f'wrong toolchain: {name}')
        if row.get('case_ids') != expected_ids: errors.append(f'wrong cases: {name}')
        parity = row.get('table_parity', {})
        if (parity.get('passed') is not True or parity.get('outside_checkout') is not True
                or parity.get('native_children') != [] or parity.get('dependency_audit', {}).get('passed') is not True):
            errors.append(f'missing native table proof: {name}')
        if name == 'Linux' and parity.get('exec_attempts') != 1: errors.append('Linux requires exactly1exec')
    if signatures and any(s != signatures[0] for s in signatures): errors.append('platform source/input/toolchain drift')
    passed = not errors and len(rows) == 2
    return {'scope': 'table-matrix', 'passed': passed, 'errors': errors,
            'platforms': [r.get('platform') for r in rows], 'Table_accepted': passed, 'M2_accepted': False}


def validate_tables(repo: Path, reference: Reference, model_probe: Path, snapshot: Path,
                    native: Path, artifact: Path, out: Path, baseline_dir: Path,
                    original_manifest: Path) -> int:
    out = out.resolve(); out.mkdir(parents=True, exist_ok=True)
    result = {'scope': 'table-local', 'platform': platform.system(), 'architecture': platform.machine(),
              'passed': False, 'M2_accepted': False, 'gates': {}}
    _write(out / 'summary.json', result)
    try:
        cases = repo / 'docs/validation/rust-migration-2026-10-18/m2-static/cases.json'
        def fingerprints():
            return _model_fingerprints(repo, reference, cases) | {
                'table_artifact': _sha(artifact), 'table_oracle': _sha(GOLDEN)}
        before = fingerprints()
        result['fingerprints'] = before
        validate_models(repo, reference, model_probe, snapshot, out / 'base', baseline_dir, original_manifest)
        base = json.loads((out / 'base/summary.json').read_text())
        result.update(gates=base.get('gates', {}), rustc=base.get('rustc'))
        if base.get('execution_error'): result['execution_error'] = base['execution_error']
        parity = compare(reference, native, artifact, out / 'table-parity')
        result.update(table_parity=parity, case_ids=parity.get('case_ids', []))
        result['gates']['table_parity'] = {'ran': True, 'passed': parity['passed'] and
            result['case_ids'] == [c['id'] for c in table_cases()]}
        if before != fingerprints(): result['execution_error'] = 'source/input drift during validation'
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        result['execution_error'] = f'{type(error).__name__}: {error}'
    result['errors'] = (['execution_error'] if result.get('execution_error') else []) + [g for g in TABLE_GATES
        if result['gates'].get(g, {}).get('ran') is not True or result['gates'][g].get('passed') is not True]
    result['passed'] = not result['errors']; result['Table_local_accepted'] = result['passed']
    _write(out / 'summary.json', result)
    return int(not result['passed'])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=['local', 'matrix'], default='local')
    parser.add_argument('--platform-receipts', type=Path)
    for name in ('reference', 'model-probe', 'snapshot', 'native', 'artifact', 'baseline-dir', 'original-manifest'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.scope == 'matrix':
        if not args.platform_receipts: parser.error('matrix requires platform-receipts')
        result = aggregate_tables(args.platform_receipts); _write(args.out / 'summary.json', result)
        return int(not result['passed'])
    if not all(getattr(args, n) for n in ('reference', 'model_probe', 'snapshot', 'native', 'artifact', 'baseline_dir', 'original_manifest')):
        parser.error('local requires all reference/model/artifact/baseline arguments')
    return validate_tables(Path.cwd(), Reference.load(args.reference), args.model_probe, args.snapshot,
                           args.native, args.artifact, args.out, args.baseline_dir, args.original_manifest)


if __name__ == '__main__':
    raise SystemExit(main())
