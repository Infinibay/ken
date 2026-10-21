"""Compatibility fixtures must come from the frozen original, without inference."""
import hashlib
import importlib.metadata
import os
from pathlib import Path

from tools.rust_migration.integration_reference import capture_profile_identities


def test_capture_binds_literal_original_profiles_and_actual_installed_versions():
    reference = Path(os.environ.get('KEN_RUST_REFERENCE', Path(__file__).resolve().parents[2]))
    record = capture_profile_identities(reference)
    source = reference / 'src/ken/retrieval/profile.py'
    assert record['original_source']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert set(record['legacy_runtime']['backends']) == {
        'static', 'model2vec', 'sentence-transformers', 'mlx', 'provided'}
    for pairs in record['legacy_runtime']['backends'].values():
        for name, actual in pairs:
            try:
                expected = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                expected = 'unavailable'
            assert actual == expected
    assert {row['label'] for row in record['profiles']} >= {
        'static', 'potion', 'torch', 'mlx', 'provided', 'joint',
        'evidence-v1', 'evidence-v2', 'evidence-v3', 'unicode'}
    for row in record['profiles']:
        assert len(row['fingerprint']) == 64
        assert set(row['vector_revisions']) == {'identity', 'behavior'}
        assert ('evidence' in row['config']) == (row['config'].get('evidence') is not None)
        if row['config'].get('contextual'):
            assert ('view_model' in row['config']['contextual']) == (
                row['config']['contextual'].get('view_model') is not None)
    assert record['invalid_encoders'] and record['invalid_profiles']
    assert all(row['error']['type'] == 'ValueError' for row in record['invalid_encoders'])
    assert record['representation_upgrade']['config']['representation_version'] == 3
