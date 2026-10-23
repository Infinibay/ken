"""Original source membership is captured independently, with pinned owners."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil

import pytest

from tools.rust_migration.reference import Reference
from tools.rust_migration.source_reference import capture_sources, compatibility_cases

REPO = Path(__file__).resolve().parents[2]
ORIGINAL = Path(os.environ.get('KEN_RUST_REFERENCE', str(REPO / '.ken/rust-migration/m0-m1/reference')))


def owner_hashes():
    baseline = json.loads((REPO / 'docs/validation/rust-migration-2026-10-18/baseline.json').read_text())
    return {r['path']: r['sha256'] for r in baseline['files']
            if r['path'] in ('src/ken/_paths.py', 'src/ken/gitignore_filter.py')}


def test_capture_uses_original_order_and_independent_exclusion_barriers(tmp_path):
    cases = [{'id': 'barriers', 'files': {
        '.gitignore': '*.env\n',
        '.kenignore': 'src/*.py\n!src/keep.py\n!secret.env\n!.ken/\n',
        'secret.env': '', 'src/keep.py': '', 'src/drop.py': '', '.ken/cache.py': ''},
        'queries': [{'path': p, 'is_dir': False} for p in
                    ('secret.env', 'src/keep.py', 'src/drop.py', '.ken/cache.py')],
        'scopes': ['.', 'src', '..']}]
    result = capture_sources(Reference.load(ORIGINAL), cases, owner_hashes(), tmp_path)
    assert result['sources'] == owner_hashes()
    assert result['runtime']['pathspec']
    row = result['cases'][0]
    assert row['ignored'] == [True, False, True, True]
    assert row['walks'][0]['entries'] == [
        {'path': '.gitignore', 'is_dir': False}, {'path': '.kenignore', 'is_dir': False},
        {'path': 'src', 'is_dir': True}, {'path': 'src/keep.py', 'is_dir': False}]
    assert row['walks'][1]['files'] == ['src/keep.py']
    assert row['walks'][2]['error']['type'] == 'ValueError'
    assert 'escapes project root' in row['walks'][2]['error']['message']


@pytest.mark.parametrize('mutation', ['changed', 'missing'])
def test_original_owner_drift_is_rejected_before_execution(tmp_path, mutation):
    root = tmp_path / 'original'
    for name in owner_hashes():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ORIGINAL / name, target)
    target = root / 'src/ken/gitignore_filter.py'
    if mutation == 'changed':
        target.write_bytes(target.read_bytes() + b'\n# changed\n')
    else:
        target.unlink()
    original = replace(Reference.load(ORIGINAL), root=root)
    with pytest.raises(ValueError, match='original source'):
        capture_sources(original, [], owner_hashes(), tmp_path / 'sandbox')


def test_fixture_definitions_are_deterministic_and_exercise_each_builtin():
    cases = compatibility_cases()
    assert cases == compatibility_cases()
    assert len({c['id'] for c in cases}) == len(cases)
    builtin = next(c for c in cases if c['id'] == 'builtins')
    assert len(builtin['queries']) == 32
    assert any(c.get('byte_files') for c in cases)
    assert any(c.get('links') for c in cases)
