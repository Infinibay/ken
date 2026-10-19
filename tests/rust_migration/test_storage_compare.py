"""Synthetic comparison mutations are not evidence of native execution."""
from copy import deepcopy
import json
import pytest
from tools.rust_migration.storage_compare import GOLDEN,RUNTIME,CORRECTIONS,compare_output,compare_reference,select_oracle

def original():return select_oracle(json.loads(GOLDEN.read_text()),'Darwin','arm64')
def native(expected):
    rows=deepcopy(expected['results'])
    for row in rows:
        if row['classification']=='integrity-correction':row['output']=deepcopy(CORRECTIONS[row['id']])
    return {'format':'ken-storage-native/1','runtime':deepcopy(RUNTIME),'results':rows,
            'metrics':{'peak_rss_bytes':1,'elapsed_ns':1}}

def test_valid_storage_histories_preserve_identity_types_metadata_slots_and_f32_values():
    expected=original();valid=native(expected);assert compare_output(expected,valid)==[]
    by_id={r['id']:i for i,r in enumerate(valid['results'])}
    for path,value in [
        (['results',0,'id'],'wrong'),(['results',0,'output','idempotent'],1),
        (['results',by_id['metadata-strings'],'output','missing'],''),
        (['results',by_id['marker-empty'],'output','metadata_after','embed_model'],None),
        (['results',by_id['slots-freed'],'output','allocations',1],[3,1]),
        (['results',by_id['migrate-mixed'],'output','rows',0,'vec_slot'],1),
        (['results',by_id['vectors-mixed'],'output','read_le_hex',0],'00000000000000000000000000000000'),
        (['results',by_id['vectors-zero'],'output','scores_le_hex'],'0000c07f'),
        (['runtime','sqlite'],'0.0'),(['runtime','little_endian'],1),
        (['metrics','peak_rss_bytes'],False),(['metrics','elapsed_ns'],0),
    ]:
        bad=deepcopy(valid);target=bad
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value
        assert compare_output(expected,bad),path
    for damage in ['missing','extra','reordered','unknown-root','unknown-output','wrong-measurements']:
        bad=deepcopy(valid)
        if damage=='missing':bad['results'].pop()
        elif damage=='extra':bad['results'].append(deepcopy(bad['results'][0]))
        elif damage=='reordered':bad['results'].reverse()
        elif damage=='unknown-root':bad['expected']={}
        elif damage=='unknown-output':bad['results'][0]['output']['unexpected']=True
        else:bad['results'][0]['measurements']=[]
        assert compare_output(expected,bad),damage

def test_corrected_integrity_cases_require_actual_rejection_preservation_and_complete_mapping():
    expected=original();valid=native(expected)
    for index,row in enumerate(valid['results']):
        if row['classification']!='integrity-correction':continue
        for key in row['output']:
            bad=deepcopy(valid);bad['results'][index]['output'][key]=False if row['output'][key] is True else True
            assert compare_output(expected,bad),(row['id'],key)
        bad=deepcopy(valid);bad['results'][index]['output']={};assert compare_output(expected,bad)

def test_storage_original_replay_binds_registered_versions_platform_owners_and_logical_outputs():
    expected=original();assert compare_reference(expected,deepcopy(expected))==[]
    for path,value in [(['oracle','python'],'3.12.10'),(['oracle','sqlite'],'3.53.2'),(['oracle','numpy'],'2.0.0'),(['oracle','sources'],{}),(['oracle','frozen_import'],False),(['oracle','encoder_singleton_unloaded'],False),(['platform'],'Linux'),(['architecture'],'x86_64'),(['reference_fingerprint'],'0'*64)]:
        bad=deepcopy(expected);target=bad
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value;assert compare_reference(expected,bad),path
    with pytest.raises(ValueError):select_oracle(json.loads(GOLDEN.read_text()),'Linux','x86_64')
    bad=json.loads(GOLDEN.read_text());bad['oracles'].append(deepcopy(bad['oracles'][0]))
    with pytest.raises(ValueError):select_oracle(bad,'Darwin','arm64')
