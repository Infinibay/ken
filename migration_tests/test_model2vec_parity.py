"""Real process parity: explicit built binary, fixed weights, no skips or compiler."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from tools.rust_migration.model_compare import compare_models

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def model_inputs():
    probe = Path(os.environ.get('KEN_MODEL_PROBE', ''))
    snapshot = Path(os.environ.get('KEN_POTION_SNAPSHOT', ''))
    assert probe.is_absolute() and probe.is_file(), 'KEN_MODEL_PROBE must name an already-built native example'
    assert snapshot.is_absolute() and snapshot.is_dir(), 'KEN_POTION_SNAPSHOT must name prepared pinned public weights'
    return probe, snapshot


def test_real_model_process_matches_frozen_oracle(reference, model_inputs, tmp_path):
    probe, snapshot = model_inputs
    result = compare_models(reference, probe, snapshot,
        ROOT / 'docs/validation/rust-migration-2026-10-18/m2-static/cases.json', tmp_path / 'parity')
    assert result['passed'], result['errors']
    assert result['case_ids'] == [c['id'] for c in json.loads((ROOT / 'docs/validation/rust-migration-2026-10-18/m2-static/cases.json').read_text())['cases']]
    assert result['outside_checkout'] and result['native_children'] == []
    assert result['dependency_audit']['passed']


def test_probe_rejects_failed_preparation_without_success_stdout(model_inputs):
    probe, _ = model_inputs
    result = subprocess.run([str(probe)], input='{}', text=True, capture_output=True, timeout=10)
    assert result.returncode == 1 and result.stdout == '' and result.stderr


def test_false_native_process_cannot_pass(reference, model_inputs, tmp_path):
    import shutil
    _, snapshot = model_inputs
    false_probe = Path(shutil.which('true')).resolve()
    result = compare_models(reference, false_probe, snapshot,
        ROOT / 'docs/validation/rust-migration-2026-10-18/m2-static/cases.json', tmp_path / 'false')
    assert not result['passed'] and result['errors']


def test_probe_rejects_changed_artifacts(model_inputs, tmp_path):
    import shutil
    probe, snapshot = model_inputs
    registration = json.loads((ROOT / 'src/ken/embedder/data/potion-code-16M-v2.json').read_text())
    copied = tmp_path / registration['revision']; copied.mkdir()
    for name in registration['artifacts']:
        shutil.copyfile(snapshot / name, copied / name)
    changed = copied / 'model.safetensors'
    with changed.open('r+b') as stream:
        first = stream.read(1); stream.seek(0); stream.write(bytes([first[0] ^ 1]))
    request = {'registration': registration, 'snapshot': str(copied),
        'legacy_runtime': {'numpy': '2.4.4', 'model2vec': '0.9.0', 'tokenizers': '0.22.2', 'safetensors': '0.8.0'},
        'cases': [{'id': 'corrupt', 'calls': [{'op': 'query', 'text': 'alpha'}]}]}
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=10)
    assert result.returncode == 1 and result.stdout == '' and 'artifact' in result.stderr
