"""The final workspace gate consumes persistent preparation, after leases close."""
import json
import os
from pathlib import Path
import sys
import tempfile

from tools.rust_migration import transformer_execution as execution


def test_clean_acquisition_ownership_gate_uses_prepared_metadata_and_workspace_target(tmp_path, monkeypatch):
    from tools.rust_migration import fastembed_evidence, fastembed_validate, transformer_validate

    for key in list(os.environ):
        if key.startswith(('KEN_', 'CARGO_TARGET_DIR')):
            monkeypatch.delenv(key)
    repo = tmp_path / 'repo'
    catalogue = repo / 'crates/ken-models/resources/transformer-catalog.json'
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text('{"models":[]}')
    runtimes = repo / 'tools/rust_migration/data/transformer-cores.json'
    runtimes.parent.mkdir(parents=True)
    runtimes.write_text('{"cores":[]}')
    index = repo / transformer_validate.REFERENCE / 'INDEX.json'
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({'chunks': [{'key': f'linux|{n}', 'receipt': str(n)} for n in range(9)]}))
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'summary.json').write_text('{}')
    recorded = tmp_path / 'recorded'
    (recorded / 'profiles').mkdir(parents=True)
    (recorded / 'summary.json').write_text('{"profiles":[]}')
    metadata = tmp_path / 'metadata'
    metadata.mkdir()
    (metadata / 'tokenizer.json').write_text('{"usable":"after acquisition"}')
    sources = tmp_path / 'acquisition'
    sources.mkdir()
    with tempfile.TemporaryDirectory(prefix='transformer-lease-', dir=sources) as leased:
        (Path(leased) / 'tokenizer.json').write_text('temporary')
    assert not list(sources.iterdir())
    target = tmp_path / 'workspace-target'
    slots = {key: str(tmp_path / key) for key in ('torch_core', 'torch_module')}
    slots.update(metadata_sources=str(metadata), workspace_target=str(target))
    preparation = tmp_path / 'preparation.json'
    preparation.write_text(json.dumps({
        'format': 'ken-transformer-preparation/1', 'platform': 'linux', 'source_files': {},
        'prepared': slots, 'capacity': {'observed_free_bytes': 3, 'next_phase_required_free_bytes': 1,
        'measured_allocated_plus_next_phase_bytes': 2, 'declared_total_bytes': 4},
    }))
    monkeypatch.setattr(execution.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(execution, 'source_identity', lambda _: {})
    monkeypatch.setattr(execution, 'read_original', lambda *_: {})
    monkeypatch.setattr(execution, 'seal_execution', lambda *_a, **_k: {})
    monkeypatch.setattr(fastembed_validate, 'fastembed_fingerprints', lambda *_: {})
    monkeypatch.setattr(fastembed_validate, 'fastembed_receipt_errors', lambda *_: [])
    monkeypatch.setattr(fastembed_evidence, 'execution_errors', lambda *_: [])
    monkeypatch.setattr(transformer_validate, 'tooling_identity', lambda _: {})
    monkeypatch.setattr(transformer_validate, 'replay_transformer_profiles', lambda *_: {'passed': True})
    monkeypatch.setattr(transformer_validate, 'validate_transformer', lambda *_: {'passed': True})
    gate = execution._gate
    checked = []

    def run_gate(root, environment, out, name, command, **kwargs):
        if name != 'transformer-ownership':
            return {'passed': True}
        # Execute a real child at the final consumer boundary, with no inherited
        # workspace target or borrowed/acquisition checkpoint to hide omissions.
        script = (
            'import json,os;from pathlib import Path;'
            f'assert Path(os.environ["CARGO_TARGET_DIR"])==Path({str(target)!r});'
            'root=Path(os.environ["KEN_TRANSFORMER_SOURCE_ROOT"]);'
            'assert root.is_absolute();'
            'assert json.loads((root/"tokenizer.json").read_text())["usable"]=="after acquisition"'
        )
        result = gate(root, environment, out, name, [sys.executable, '-c', script])
        checked.append(result)
        return result

    monkeypatch.setattr(execution, '_gate', run_gate)
    result = execution.execute_platform(repo, preparation, legacy, sources, tmp_path / 'out',
                                        acquire=True, recorded_profiles=recorded)
    assert len(checked) == 1
    assert result['passed'], (tmp_path / 'out/transformer-ownership.log').read_text()
