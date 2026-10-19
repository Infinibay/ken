"""Context expectations must come from the frozen original, before native code."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tools.rust_migration.reference import freeze_reference
from tools.rust_migration.context_fixtures import build_fixture
from tools.rust_migration.context_reference import capture, context_cases, stderr_errors


@pytest.fixture
def original(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    source = tmp_path / 'source'
    shutil.copytree(repo / 'src', source / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    (source / 'tests').mkdir()
    shutil.copy2(repo / 'tests/test_context_encoder.py', source / 'tests/test_context_encoder.py')
    return freeze_reference(source, tmp_path / 'frozen')


def test_frozen_context_capture_preserves_prefix_raw_vectors_and_lazy_empty(original, tmp_path):
    snapshot, definition, helper = build_fixture(original, tmp_path / 'fixture')
    assert helper['path'] == 'tests/test_context_encoder.py'
    assert helper['sha256'] == hashlib.sha256((original.root / helper['path']).read_bytes()).hexdigest()
    cases = [
        {'id': 'empty', 'prepare': False, 'calls': [{'op': 'passages', 'texts': []}]},
        {'id': 'policy', 'prepare': True, 'calls': [
            {'op': 'tokens', 'kind': 'query', 'text': 'red'},
            {'op': 'tokens', 'kind': 'passage', 'text': 'red'},
            {'op': 'query', 'text': 'red'},
            {'op': 'passages', 'texts': ['red', '', 'red red']},
        ]},
    ]
    result = capture(original, snapshot, tmp_path / 'result.json', definition=definition, cases=cases)
    assert result['oracle']['frozen_import'] is True
    assert result['results'][0]['calls'] == [[]]
    assert result['results'][0]['session_loaded'] is False
    calls = result['results'][1]['calls']
    assert calls[:2] == [{'ids': [4, 1, 2, 5], 'attention_mask': [1]*4},
                         {'ids': [4, 2, 5], 'attention_mask': [1]*3}]
    assert calls[2][:2] == [12., 4.] and calls[2][2:] == [0.]*766
    assert [row[:2] for row in calls[3]] == [[11., 3.], [9., 2.], [13., 4.]]
    assert all(len(row) == 768 for row in calls[3])
    assert result['spec']['backend'] == 'provided' and result['spec']['batch_size'] == 1
    assert result['spec']['dtype'] == 'float32' and result['spec']['sequence_length'] == 512
    assert result['spec_key'].startswith('test/context@' + result['spec']['revision'] + ':')
    assert result['tokenizer_revision'] == hashlib.sha256(b'[]').hexdigest()[:16]
    assert result['results'][1]['providers'] == ['CPUExecutionProvider']
    assert result['results'][1]['peak_after_inference_bytes'] >= result['results'][1]['peak_after_load_bytes'] > 0
    assert json.loads((tmp_path / 'result.json').read_text()) == result
    (snapshot / 'tokenizer.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='artifact'):
        capture(original, snapshot, tmp_path / 'bad.json', definition=definition, cases=cases)


def test_context_original_identity_and_source_drift_are_not_hidden(original, tmp_path):
    snapshot, definition, _ = build_fixture(original, tmp_path / 'fixture')
    cases = [{'id': 'query', 'prepare': True, 'calls': [{'op': 'query', 'text': 'red'}]}]
    revisions = []
    for index, change in enumerate([{}, {'query_prefix': 'search '}, {'document_projection': 'other'}]):
        result = capture(original, snapshot, tmp_path / f'{index}.json', definition=definition | change, cases=cases)
        revisions.append(result['spec']['revision'])
    assert len(set(revisions)) == 3
    (original.root / 'src/ken/embedder/contextual_onnx.py').write_text('DRIFT=True\n')
    with pytest.raises(ValueError, match='reference'):
        capture(original, snapshot, tmp_path / 'bad.json', definition=definition, cases=cases)


def test_context_fixed_histories_and_diagnostic_policy():
    cases = context_cases()
    assert len(cases) == len({c['id'] for c in cases}) == 20
    assert [c['id'] for c in cases if not c['prepare']] == ['empty-passages']
    warning = 'onnxruntime cpuid_info warning: Unknown CPU vendor. cpuinfo_vendor value: 0\n'
    assert stderr_errors('', 'Darwin') == []
    assert stderr_errors('', 'Linux') == []
    assert stderr_errors(warning, 'Linux') == []
    assert stderr_errors(warning, 'Darwin')
    assert stderr_errors(warning*2, 'Linux')
    assert stderr_errors(warning+'unexpected\n', 'Linux')


def test_generated_context_fixtures_record_original_errors_and_extra_row_gap(original, tmp_path, monkeypatch):
    from tools.rust_migration.context_fixtures import generate
    monkeypatch.chdir(tmp_path)
    out = Path('fixtures')
    manifest = generate(original, out)
    assert json.loads((out / 'manifest.json').read_text()) == manifest
    assert len(manifest['valid']) == 1 and len(manifest['invalid']) == 8
    invalid = {r['id']: r for r in manifest['invalid']}
    assert invalid['extra-row']['original_accepted'] is True
    assert all(r['native_reject'] for r in invalid.values())
    assert all(not r['original_accepted'] for name, r in invalid.items() if name != 'extra-row')
    oracle = json.loads((out / manifest['valid'][0]['oracle']).read_text())
    assert oracle['results'][0]['session_loaded'] is False
    assert oracle['results'][1]['calls'][0]['ids'] == [4, 1, 2, 5]
    for row in manifest['files']:
        assert hashlib.sha256((out / row['path']).read_bytes()).hexdigest() == row['sha256']
