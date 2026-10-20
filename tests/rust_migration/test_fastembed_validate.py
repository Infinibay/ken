"""Receipt fixtures exercise the gate; synthetic data cannot certify acceptance."""
from copy import deepcopy
import json
from pathlib import Path

from test_storage_validate import storage_row
from tools.rust_migration.fastembed_validate import (
    FASTEMBED_GATES, FASTEMBED_KEYS, fastembed_receipt_errors, aggregate_fastembed,
    fastembed_input_fingerprints,
)

PUBLIC=Path(__file__).resolve().parents[2]/'docs/validation/rust-migration-2026-10-20/m2-fastembed-native'


def fastembed_row(folder='linux'):
    base=storage_row(folder)
    parity=json.loads((PUBLIC/f'native-{folder}-attempt1/summary.json').read_bytes())
    ownership=json.loads((PUBLIC/f'ownership-{folder}-attempt1/summary.json').read_bytes())
    # Historical evidence has a different full reference manifest, but the same
    # frozen application. This fixture binds the current composed base explicitly.
    parity['reference_fingerprint']=base['storage_parity']['reference_fingerprint']
    # Only this explicitly synthetic fixture rebinds controller identities.
    # Published historical receipts remain immutable and fail current acceptance.
    import hashlib
    tools=Path(__file__).resolve().parents[2]/'tools/rust_migration'
    parity['tooling']={name:hashlib.sha256((tools/name).read_bytes()).hexdigest()
        for name in ['fastembed_compare.py','fastembed_process.py']}
    binding={'ran':True,'passed':True,'built_sha256':parity['native_sha256'],
             'supplied_sha256':parity['native_sha256']}
    return {'scope':'fastembed-local','synthetic_fixture':True,'platform':base['platform'],
        'architecture':base['architecture'],'passed':True,'M2_accepted':False,'rustc':base['rustc'],
        'fingerprints':base['fingerprints']|fastembed_input_fingerprints(),
        'storage_base':base,'fastembed_release':binding,'fastembed_parity':parity,
        'fastembed_ownership':ownership,'gates':deepcopy(base['gates'])|{
            'fastembed_release':binding,'fastembed_parity':{'ran':True,'passed':True},
            'fastembed_ownership':{'ran':True,'passed':True}}}


def test_fastembed_requires34_gates33_current_inputs_and_complete_bound_base():
    row=fastembed_row();current=deepcopy(row['fingerprints'])
    assert len(FASTEMBED_GATES)==34 and len(FASTEMBED_KEYS)==33
    assert fastembed_receipt_errors(row,current)==[]
    for gate in FASTEMBED_GATES:
        bad=deepcopy(row);bad['gates'][gate]['passed']=False
        assert fastembed_receipt_errors(bad,current),gate
    for key in FASTEMBED_KEYS:
        bad=deepcopy(row);bad['fingerprints'][key]='0'*64
        assert fastembed_receipt_errors(bad,current),key
    for path,value in [(['M2_accepted'],True),(['platform'],'Darwin'),(['architecture'],'x86_64'),
        (['rustc'],'rustc 1.94.0'),(['fastembed_release','supplied_sha256'],'0'*64),
        (['fastembed_parity','models'],[]),(['fastembed_parity','case_ids'],[]),
        (['fastembed_parity','producer','engine'],'python'),
        (['fastembed_parity','producer','source_sha256'],'0'*64),
        (['fastembed_parity','core_identity','api'],24),
        (['fastembed_parity','reference_fingerprint'],'0'*64),
        (['fastembed_parity','tooling','fastembed_compare.py'],'0'*64),
        (['fastembed_parity','tooling','fastembed_process.py'],'0'*64),
        (['fastembed_ownership','models'],[]),(['fastembed_ownership','native_sha256'],'0'*64),
        (['storage_base','storage_parity','runtime','sqlite'],'wrong')]:
        bad=deepcopy(row);target=bad
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value
        assert fastembed_receipt_errors(bad,current),path


def test_fastembed_matrix_rejects_synthetic_and_missing_platforms(tmp_path):
    for folder in ['linux','macos']:
        dest=tmp_path/folder;dest.mkdir();row=fastembed_row(folder)
        (dest/'summary.json').write_text(json.dumps(row))
    result=aggregate_fastembed(tmp_path,expected_fingerprints=row['fingerprints'])
    assert result['FastEmbed_accepted'] is False and result['M2_accepted'] is False
    assert any('synthetic' in error for error in result['errors'])
    (tmp_path/'linux/summary.json').unlink()
    result=aggregate_fastembed(tmp_path,expected_fingerprints=row['fingerprints'])
    assert any('exactly' in error for error in result['errors'])
