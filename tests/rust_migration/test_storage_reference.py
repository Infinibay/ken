"""Storage expectations come from real original operations before native code."""
import json
import os
from pathlib import Path
import sys
from copy import deepcopy
import struct

import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_original_storage_histories_cover_valid_data_and_declared_integrity_corrections():
    from tools.rust_migration.storage_reference import storage_cases
    cases=storage_cases();by_id={case['id']:case for case in cases}
    assert len(by_id)==len(cases)
    required={'schema-fresh','schema-legacy','metadata-strings','marker-null','marker-empty','marker-absent','marker-stored',
        'marker-vector-blob-empty','marker-vector-slot-zero','marker-vector-slot-negative',
        'slots-freed','slots-rollback','cascade','unique-slot','vectors-boundary','vectors-sparse',
        'vectors-duplicates','vectors-zero','vectors-mixed','migrate-mixed','migrate-twice',
        'compact','vacuum','correction-manifest-space','correction-manifest-dtype',
        'correction-manifest-capacity','correction-norm-overflow','correction-nan',
        'correction-inf','correction-sql-error','correction-compaction-interruption'}
    assert required<=by_id.keys()
    for case in cases:
        assert case['classification']==('integrity-correction' if case['id'].startswith('correction-') else 'compatibility')
        assert isinstance(case['input'],dict) and isinstance(case['input']['op'],str)
        assert 'expected' not in case['input'] and 'source_setup' not in case['input']


def test_capture_invokes_verified_original_and_preserves_source_hashes(tmp_path):
    from tools.rust_migration.storage_reference import capture_storage,storage_cases
    from tools.rust_migration.reference import Reference,verify_reference
    reference=Reference.load(Path(os.environ.get('KEN_RUST_REFERENCE',ROOT/'.ken/rust-migration/m0-m1/reference')))
    result=capture_storage(reference,tmp_path/'oracle.json')
    assert result['scope']=='original-storage/1'
    assert result['oracle']['frozen_import'] is True
    assert result['oracle']['encoder_singleton_unloaded'] is True
    assert set(result['oracle']['sources'])=={'src/ken/db.py','src/ken/schema.sql','src/ken/vectors.py',
        'src/ken/embedder/__init__.py','src/ken/_paths.py'}
    assert [r['id'] for r in result['results']]==[c['id'] for c in storage_cases()]
    rows={r['id']:r for r in result['results']}
    assert rows['slots-freed']['output']['allocations']==[[0,1,2],[1,3]]
    assert rows['slots-rollback']['output']['high_water']==0
    assert rows['marker-null']['output']['metadata_after']=={'embed_doc_space':'2','embed_model':'user/model','unrelated':'keep'}
    assert rows['marker-empty']['output']['metadata_after']['embed_model']==''
    assert rows['marker-absent']['output']['metadata_after']==rows['marker-null']['output']['metadata_after']
    assert rows['marker-stored']['output']['metadata_after']['embed_model']=='stored/model'
    for name in ['marker-vector-blob-empty','marker-vector-slot-zero','marker-vector-slot-negative']:
        assert rows[name]['output']['metadata_after'].get('embed_model') is None
    assert rows['vectors-zero']['output']['read_le_hex']==['00000000000000000000000000000000']
    assert rows['migrate-twice']['output']['moved']==[{'ci_files':1,'ci_symbols':0,'ci_intent_sources':0},
        {'ci_files':0,'ci_symbols':0,'ci_intent_sources':0}]
    assert rows['correction-compaction-interruption']['output']['complete_mapping'] is False
    assert rows['correction-norm-overflow']['output']['read_le_hex']==['0000000000000000']
    assert verify_reference(reference.root,reference.manifest_path)==[]
    assert json.loads((tmp_path/'oracle.json').read_text())==result


def test_incomplete_reference_fails_before_publishing_a_storage_oracle(tmp_path):
    from tools.rust_migration.storage_reference import capture_storage
    from tools.rust_migration.reference import Reference
    root=tmp_path/'empty';root.mkdir();manifest=root/'reference-manifest.json'
    manifest.write_text(json.dumps({'files':[],'scope':['src/ken/**']}))
    reference=Reference(root,manifest,'0'*64,Path(sys.executable))
    with pytest.raises(ValueError,match='reference'):
        capture_storage(reference,tmp_path/'out/oracle.json')
    assert not (tmp_path/'out').exists()


def test_storage_logical_comparison_preserves_types_and_declared_f32_tolerance():
    from tools.rust_migration.storage_reference import logical_storage_differences
    def bits(value):return struct.pack('<f',value).hex()
    expected=[{'id':'fixture','classification':'compatibility','output':{
        'read_le_hex':[bits(0.6)],'score_count':1,'flag':False},'measurements':{'blocks':8}}]
    actual=deepcopy(expected);actual[0]['output']['read_le_hex']=[bits(0.6000001)]
    actual[0]['measurements']={'blocks':16}
    assert logical_storage_differences(expected,actual)==[]
    boundary=deepcopy(expected);boundary[0]['output']['read_le_hex']=[bits(1.0)]
    within=deepcopy(boundary);within[0]['output']['read_le_hex']=[bits(1.0000015)]
    assert logical_storage_differences(boundary,within)==[]
    for name,value in [('read_le_hex',[bits(0.61)]),('read_le_hex',['0000c07f']),
                       ('score_count',True),('flag',0)]:
        bad=deepcopy(actual);bad[0]['output'][name]=value
        assert logical_storage_differences(expected,bad),(name,value)
    for change in ['missing','extra','id','classification']:
        bad=deepcopy(actual)
        if change=='missing':bad=[]
        elif change=='extra':bad[0]['output']['unknown']=1
        else:bad[0][change]='other'
        assert logical_storage_differences(expected,bad),change
