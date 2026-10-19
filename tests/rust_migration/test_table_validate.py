"""A table matrix cannot inherit acceptance from an older source or one OS."""
from copy import deepcopy
import json

from tools.rust_migration.model_validate import REQUIRED_GATES
from tools.rust_migration.table_validate import aggregate_tables


def test_matrix_requires_current_matching_base_and_real_table_proof(tmp_path):
    def write(rows):
        for path in tmp_path.glob('*/summary.json'): path.unlink()
        for index, row in enumerate(rows):
            path = tmp_path / str(index) / 'summary.json'
            path.parent.mkdir(exist_ok=True); path.write_text(json.dumps(row))
        return aggregate_tables(tmp_path, expected_ids=['one'])
    base = {'scope': 'table-local', 'platform': 'Darwin', 'passed': True,
        'M2_accepted': False, 'case_ids': ['one'], 'rustc': 'rustc 1.95.0 (same)',
        'fingerprints': {'native_source': 'a'*64, 'reference_source': 'b'*64,
            'cases': 'c'*64, 'validator': 'd'*64, 'oracle': 'e'*64, 'registration': 'f'*64,
            'table_artifact': '1'*64, 'table_oracle': '2'*64},
        'gates': {g: {'ran': True, 'passed': True} for g in (*REQUIRED_GATES, 'table_release', 'table_parity')},
        'table_release': {'ran': True, 'passed': True, 'built_sha256': '3'*64, 'supplied_sha256': '3'*64},
        'table_parity': {'passed': True, 'outside_checkout': True, 'native_children': [],
                         'native_sha256': '3'*64, 'dependency_audit': {'passed': True}, 'exec_attempts': 1}}
    linux = deepcopy(base); linux['platform'] = 'Linux'
    assert write([base, linux])['Table_accepted'] is True
    assert write([base, linux])['M2_accepted'] is False
    assert not write([base])['passed']
    assert not write([base, base])['passed']
    for field in ['native_source', 'table_artifact', 'table_oracle', 'validator']:
        bad = deepcopy(linux); bad['fingerprints'][field] = '0'*64
        assert not write([base, bad])['passed']
    for gate in (*REQUIRED_GATES, 'table_release', 'table_parity'):
        bad = deepcopy(linux); bad['gates'][gate]['passed'] = False
        assert not write([base, bad])['passed']
    for key, value in [('exec_attempts', 2), ('outside_checkout', False),
                       ('native_children', ['python']), ('dependency_audit', {'passed': False})]:
        bad = deepcopy(linux); bad['table_parity'][key] = value
        assert not write([base, bad])['passed']
    bad = deepcopy(linux); bad['execution_error'] = 'interrupted'
    assert not write([base, bad])['passed']
    bad = deepcopy(linux); bad['case_ids'] = []
    assert not write([base, bad])['passed']
    for key, value in [('passed', False), ('built_sha256', '4'*64), ('supplied_sha256', '4'*64)]:
        bad = deepcopy(linux); bad['table_release'][key] = value
        assert not write([base, bad])['passed']
    bad = deepcopy(linux); bad.pop('table_release')
    assert not write([base, bad])['passed']
    bad = deepcopy(linux); bad['table_parity']['native_sha256'] = '4'*64
    assert not write([base, bad])['passed']


def test_table_binding_rejects_stale_and_missing_executables(tmp_path):
    from tools.rust_migration.table_validate import bind_table_probe
    built = tmp_path / 'target/release/examples/table_probe'
    built.parent.mkdir(parents=True); built.write_bytes(b'fresh native release')
    supplied = tmp_path / 'outside-table-probe'; supplied.write_bytes(b'fresh native release')
    result = bind_table_probe(tmp_path, supplied)
    assert result['ran'] and result['passed']
    assert result['built_sha256'] == result['supplied_sha256']
    supplied.write_bytes(b'stale native release')
    assert not bind_table_probe(tmp_path, supplied)['passed']
    supplied.unlink()
    assert not bind_table_probe(tmp_path, supplied)['passed']
    built.unlink()
    assert not bind_table_probe(tmp_path, supplied)['passed']


def test_table_process_requires_explicit_probe_even_with_a_model_sibling(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    import pytest
    path = Path(__file__).resolve().parents[2] / 'migration_tests/test_static_table_parity.py'
    spec = importlib.util.spec_from_file_location('table_process_boundary', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    model = tmp_path / 'model_probe'; model.touch()
    sibling = tmp_path / 'table_probe'; sibling.touch()
    monkeypatch.setenv('KEN_MODEL_PROBE', str(model))
    monkeypatch.delenv('KEN_TABLE_PROBE', raising=False)
    with pytest.raises(AssertionError, match='explicit'):
        module.probe()
    explicit = tmp_path / 'selected-table-probe'; explicit.touch()
    monkeypatch.setenv('KEN_TABLE_PROBE', str(explicit))
    assert module.probe() == explicit
