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
        'gates': {g: {'ran': True, 'passed': True} for g in (*REQUIRED_GATES, 'table_parity')},
        'table_parity': {'passed': True, 'outside_checkout': True, 'native_children': [],
                         'dependency_audit': {'passed': True}, 'exec_attempts': 1}}
    linux = deepcopy(base); linux['platform'] = 'Linux'
    assert write([base, linux])['Table_accepted'] is True
    assert write([base, linux])['M2_accepted'] is False
    assert not write([base])['passed']
    assert not write([base, base])['passed']
    for field in ['native_source', 'table_artifact', 'table_oracle', 'validator']:
        bad = deepcopy(linux); bad['fingerprints'][field] = '0'*64
        assert not write([base, bad])['passed']
    for gate in (*REQUIRED_GATES, 'table_parity'):
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
