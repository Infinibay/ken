"""The real static-table executable must work outside the source checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.rust_migration.table_compare import compare

ROOT = Path(__file__).resolve().parents[1]


def probe():
    value = Path(os.environ.get('KEN_TABLE_PROBE', ''))
    assert value.is_absolute() and value.is_file(), 'an explicit already-built KEN_TABLE_PROBE is required'
    return value


def artifact():
    return ROOT / 'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz'


def test_real_static_table_process_matches_frozen_python(reference, tmp_path):
    result = compare(reference, probe(), artifact(), tmp_path / 'parity')
    assert result['passed'], result['errors']
    assert len(result['case_ids']) == 16
    assert result['outside_checkout'] and result['native_children'] == []
    assert result['dependency_audit']['passed']


def test_false_native_table_process_fails(reference, tmp_path):
    result = compare(reference, Path(shutil.which('true')).resolve(), artifact(), tmp_path / 'false')
    assert not result['passed'] and result['errors']


def test_table_probe_rejects_missing_or_corrupt_input_without_success(tmp_path):
    for request in [{}, {'artifact': str(tmp_path / 'absent'), 'cases': []}]:
        result = subprocess.run([str(probe())], input=json.dumps(request), text=True,
                                capture_output=True, timeout=10)
        assert result.returncode == 1 and not result.stdout and result.stderr
    bad = tmp_path / 'bad.npz'; bad.write_bytes(b'not a table')
    result = subprocess.run([str(probe())], input=json.dumps({'artifact': str(bad),
        'cases': [{'id': 'bad', 'calls': [{'op': 'query', 'text': 'alfa'}]}]}),
        text=True, capture_output=True, timeout=10)
    assert result.returncode == 1 and not result.stdout and result.stderr
