"""Native evidence must preserve the independently frozen paired histories."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from tools.rust_migration.ettin_compare import RUNTIME, compare_output, select_oracle

ROOT=Path(__file__).resolve().parents[2]


def evidence():
    document=json.loads((ROOT/'docs/validation/rust-migration-2026-10-19/m2-ettin/reference.json').read_text())
    expected=select_oracle(document,'Darwin','arm64')
    cores=json.loads((ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_text())
    core=next(row for row in cores['libraries'] if row['os']=='macos')
    actual={'artifacts':deepcopy(expected['artifacts']),
        'preparation':{'fresh_cache':True,'reused_without_source':True,
            'source_artifacts':deepcopy(expected['source_artifacts']),
            'artifacts':deepcopy(expected['artifacts']),
            'recipe_key':hashlib.sha256(json.dumps(expected['definition'],sort_keys=True).encode()).hexdigest()},
        'prepare_ns':1,'peak_after_prepare_bytes':1000,
        'runtime':RUNTIME|{'native_core':core},'results':deepcopy(expected['results'])}
    for index,row in enumerate(actual['results']):
        row['peak_before_calls_bytes']=1000+2000*index
        row['peak_after_calls_bytes']=2000+2000*index
        for call in row['calls']:
            if isinstance(call,dict) and 'error' in call:
                call['error']['type']='ModelError'
                call['error']['message']='invalid model tokenizer: '+call['error']['message']
    return document,expected,actual,core


def test_ettin_comparator_accepts_frozen_local_history_with_measured_native_phases():
    _,expected,actual,core=evidence()
    assert len(actual['results'])==23
    assert compare_output(expected,actual,core)==[]


def test_ettin_comparator_rejects_identity_preparation_and_runtime_shortcuts():
    _,expected,actual,core=evidence()
    for key in ['fresh_cache','reused_without_source']:
        bad=deepcopy(actual);bad['preparation'][key]=False
        assert compare_output(expected,bad,core),key
    for field in ['artifacts','source_artifacts']:
        bad=deepcopy(actual);bad['preparation'][field]={}
        assert compare_output(expected,bad,core),field
    bad=deepcopy(actual);bad['preparation']['recipe_key']='0'*64
    assert compare_output(expected,bad,core)
    for key,value in [('api',31),('sha256','0'*64),('os','linux')]:
        bad=deepcopy(actual);bad['runtime']['native_core']=core|{key:value}
        assert compare_output(expected,bad,core),key
    for key,value in [('device','cuda'),('cpu_arena',1),('inter_threads',True)]:
        bad=deepcopy(actual);bad['runtime'][key]=value
        assert compare_output(expected,bad,core),key
    for key in ['prepare_ns','peak_after_prepare_bytes']:
        for value in [0,True,1.5]:
            bad=deepcopy(actual);bad[key]=value
            assert compare_output(expected,bad,core),(key,value)


def test_ettin_comparator_rejects_tokens_logits_details_and_error_state_drift():
    _,expected,actual,core=evidence()
    def mutate(change):
        bad=deepcopy(actual);change(bad)
        assert compare_output(expected,bad,core)
    mutate(lambda d:d['results'].reverse())
    mutate(lambda d:d['results'].pop())
    mutate(lambda d:d['results'][0].update(session_loaded=True))
    mutate(lambda d:d['results'][0]['calls'][0]['details'].update(pad_id=None))
    mutate(lambda d:d['results'][0]['calls'][0]['details'].update(token_ms=True))
    for field,value in [('ids',[1]),('attention_mask',[1]),('overflowing',1)]:
        mutate(lambda d:d['results'][1]['calls'][0][0].update({field:value}))
    for value in [float('nan'),float('inf'),True,999.,10**1000]:
        mutate(lambda d:d['results'][1]['calls'][1]['scores'].__setitem__(0,value))
    for field,value in [('pair_tokens',[]),('truncated_documents',True),('pad_id',0),
                        ('token_ms',-1.),('inference_ms',float('inf'))]:
        mutate(lambda d:d['results'][1]['calls'][1]['details'].update({field:value}))
    for field,value in [('providers',[]),('cpu_arena',False),('intra_threads',1),('inter_threads',True),
                        ('peak_after_calls_bytes',500),('calls_ns',False)]:
        mutate(lambda d:d['results'][1].update({field:value}))
    error_index=next(i for i,r in enumerate(expected['results'])
                     if any(isinstance(c,dict) and 'error' in c for c in r['calls']))
    mutate(lambda d:d['results'][error_index]['calls'][0].update(error={'type':'ModelError','message':'unrelated failure'}))
    bad_expected=deepcopy(expected)
    bad_expected['results'][1]['calls'][1]['scores'][0]=float('nan')
    assert compare_output(bad_expected,actual,core), 'a nonfinite original cannot authorize parity'


def test_ettin_comparator_keeps_fixed_tolerance_exact_zero_and_result_shape():
    _,expected,actual,core=evidence()
    want=expected['results'][1]['calls'][1]['scores'][0]
    tolerance=1e-5+1e-5*abs(want)
    near=deepcopy(actual);near['results'][1]['calls'][1]['scores'][0]=want+tolerance*.5
    assert compare_output(expected,near,core)==[]
    far=deepcopy(actual);far['results'][1]['calls'][1]['scores'][0]=want+tolerance*1.1
    assert compare_output(expected,far,core)
    zero=deepcopy(expected);zero['results'][1]['calls'][1]['scores'][0]=0.
    exact=deepcopy(actual);exact['results'][1]['calls'][1]['scores'][0]=0.
    assert compare_output(zero,exact,core)==[]
    exact['results'][1]['calls'][1]['scores'][0]=1e-7
    assert compare_output(zero,exact,core), 'zero is exact even within general tolerance'
    extra=deepcopy(actual);extra['expected_scores']=[29.]
    assert compare_output(expected,extra,core), 'unexpected output fields must not hide supplied expectations'


def test_ettin_oracle_selection_requires_exact_platform_and_architecture():
    document,_,_,_=evidence()
    for system,architecture in [('Linux','arm64'),('Darwin','x86_64')]:
        try:select_oracle(document,system,architecture)
        except ValueError:pass
        else:raise AssertionError('mismatched platform oracle accepted')
    bad=deepcopy(document);bad['platforms']['Darwin/arm64']['platform']='Linux'
    try:select_oracle(bad,'Darwin','arm64')
    except ValueError:pass
    else:raise AssertionError('mislabeled oracle accepted')


def test_original_replay_requires_frozen_provenance_and_the_same_local_behavior():
    from tools.rust_migration.ettin_compare import compare_reference
    _,expected,_,_=evidence()
    assert compare_reference(expected,deepcopy(expected))==[]
    for field,value in [('platform','Linux'),('source_artifacts',{}),('artifacts',{}),('cases',[])]:
        bad=deepcopy(expected);bad[field]=value
        assert compare_reference(expected,bad),field
    bad=deepcopy(expected);bad['oracle']['frozen_import']=1
    assert compare_reference(expected,bad)
    bad=deepcopy(expected);bad['oracle']['runtime']['onnxruntime']='1.25.2'
    assert compare_reference(expected,bad)
    bad=deepcopy(expected);bad['results'][1]['calls'][1]['scores'][0]+=1.
    assert compare_reference(expected,bad)
    bad=deepcopy(expected);bad['results'][1]['calls'][0][0]['ids']=[0]
    assert compare_reference(expected,bad)
