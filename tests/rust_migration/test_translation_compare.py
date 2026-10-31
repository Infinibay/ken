"""Reject changed native data, language decisions, neural histories and provenance."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.rust_migration.translation_compare import compare_output, compare_reference, select_oracle

ROOT=Path(__file__).resolve().parents[2]


def evidence(system='Darwin',arch='arm64'):
    document=json.loads((ROOT/'docs/validation/rust-migration-2026-10-19/m2-translation/reference.json').read_text())
    expected=next(r for r in document['oracles'] if r['platform']==system and r['architecture']==arch)
    actual={'format':'ken-translation-native/1',
        'preparation':{'fresh_cache':True,'reused_without_source':True,'source_artifacts':deepcopy(expected['source_artifacts']),
            'artifacts':deepcopy(expected['prepared_artifacts']),'recipe_key':expected['recipe_sha256']},
        'prepare_ns':1,'runtime':{'engine':'rust','ken_models':'0.18.0'},
        'memory_samples':deepcopy(expected['memory_samples']),'results':deepcopy(expected['results'])}
    identity={'ct2rs_crate':'0.10.1','ctranslate2_source':'4.8.2','sentencepiece_crate':'0.13.2',
        'sentencepiece_source':'0.2.1','float_backend':'Accelerate' if system=='Darwin' else 'OpenBLAS0.3.26',
        'int8_backend':'Ruy','configured_device':'cpu','configured_compute_type':'int8','intra_threads':2,
        'inter_threads':1,'observed_replicas':1,'beam_size':1,'max_input_length':1024,'max_decoding_length':256}
    for case,row in zip(expected['cases'],actual['results'],strict=True):
        row['actual_runtime']=deepcopy(identity) if row['calls'][-1]['runtime_loaded'] else None
        for call in row['calls']:
            if 'error' not in call:continue
            original=call['error']
            if original['type']=='RuntimeError':
                call['error']={'type':'ModelError','kind':'inference','message':original['message']}
            elif case.get('missing_assets'):
                call['error']={'type':'ModelError','kind':'artifact','message':
                    'model artifact missing or changed: explicit translation source required for preparation'}
            else:
                call['error']={'type':'ModelError','kind':'artifact','message':'model artifact missing or changed: model.bin'}
    return document,expected,actual


def test_exact_native_histories_accept_both_platform_originals_with_actual_measurements():
    for system,arch in [('Darwin','arm64'),('Linux','aarch64')]:
        _,expected,actual=evidence(system,arch)
        assert len(actual['results'])==29
        assert compare_output(expected,actual)==[]

def x86_evidence(backend):
    from tools.rust_migration.translation_compare import native_identity, _native_error
    from tools.rust_migration.x86_translation_reference import load
    expected=load(ROOT)
    actual={'format':'ken-translation-native/1','preparation':dict(fresh_cache=True,reused_without_source=True,
        source_artifacts=expected['source_artifacts'],artifacts=expected['prepared_artifacts'],recipe_key=expected['recipe_sha256']),
        'prepare_ns':1,'runtime':{'engine':'rust','ken_models':'0.18.0'},
        'memory_samples':deepcopy(expected['memory_samples']),'results':deepcopy(expected['results'])}
    runtime=native_identity('Linux','x86_64',backend=backend)
    for case,row in zip(expected['cases'],actual['results'],strict=True):
        row['actual_runtime']=deepcopy(runtime)if row['calls'][-1]['runtime_loaded']else None
        for call in row['calls']:
            if 'error'in call:call['error']=_native_error(case,call['error'])
    return expected,actual


def test_amd_original_cannot_qualify_mkl_even_if_all_numerical_answers_match():
    expected,actual=x86_evidence('MKL')
    errors=compare_output(expected,actual,backend='MKL')
    assert errors, 'AMD reference plus MKL labels must never establish independent MKL parity'
    assert any('independent' in error.lower() and 'MKL' in error for error in errors), errors


def test_x86_comparison_requires_an_explicit_registered_native_backend():
    from tools.rust_migration.translation_compare import native_identity
    expected,actual=x86_evidence('DNNL')
    assert not compare_output(expected,actual,backend='DNNL')
    assert compare_output(expected,actual)
    assert compare_output(expected,actual,backend='MKL')
    for backend in ('DNNL','MKL'):
        runtime=native_identity('Linux','x86_64',backend=backend)
        assert runtime['native_binding']=='ken-translation/1'and 'ct2rs_crate'not in runtime
    for backend in (None,'Ruy','OpenBLAS0.3.26'):
        with pytest.raises(ValueError):native_identity('Linux','x86_64',backend=backend)


def test_actual_mixed_or_unregistered_backend_cannot_hide_behind_dnnl_declaration():
    for float_backend,int8_backend in [('MKL','MKL'),('DNNL','MKL'),('MKL','DNNL')]:
        expected,actual=x86_evidence('DNNL')
        runtime=next(row['actual_runtime']for row in actual['results']if row['actual_runtime'])
        runtime.update(float_backend=float_backend,int8_backend=int8_backend)
        errors=compare_output(expected,actual,backend='DNNL')
        assert any('independent' in error and f'{float_backend}/{int8_backend}'in error for error in errors),errors


def test_changed_tokens_hypotheses_text_failure_boundaries_and_lazy_states_are_rejected():
    _,expected,actual=evidence()
    def rejected(change):
        bad=deepcopy(actual);change(bad)
        assert compare_output(expected,bad)
    rejected(lambda d:d['results'].reverse())
    rejected(lambda d:d['results'].pop())
    rejected(lambda d:d['results'][0]['calls'][0].update(output='changed English'))
    rejected(lambda d:d['results'][0]['calls'][0].update(runtime_loaded=True))
    rejected(lambda d:d['results'][6]['calls'][0]['trace'].update(source_ids=[1]))
    rejected(lambda d:d['results'][6]['calls'][0]['trace'].update(source_pieces_with_eos=['wrong']))
    rejected(lambda d:d['results'][6]['calls'][0]['trace'].update(hypotheses=[['wrong']]))
    rejected(lambda d:d['results'][6]['calls'][0]['trace'].update(decoded='wrong'))
    rejected(lambda d:d['results'][6]['calls'][0]['trace']['options'].update(beam_size=True))
    for case in ['source-boundary513','missing-assets-lazy','corrupt-assets-lazy']:
        index=next(i for i,r in enumerate(actual['results']) if r['id']==case)
        call_index=next(i for i,c in enumerate(actual['results'][index]['calls']) if 'error' in c)
        for key,value in [('type','RuntimeError'),('kind','registration'),('message','unrelated failure')]:
            rejected(lambda d:d['results'][index]['calls'][call_index]['error'].update({key:value}))
    rejected(lambda d:d['results'][6].update(revision='0'*64))
    rejected(lambda d:d['results'][6]['identity'].update(intra_threads=1))
    rejected(lambda d:d.update(expected_outputs=['precomputed']))


def test_changed_preparation_recipe_compilation_backends_and_peak_measurements_are_rejected():
    _,expected,actual=evidence()
    for key,value in [('fresh_cache',False),('reused_without_source',False),('recipe_key','0'*64),
                      ('source_artifacts',{}),('artifacts',{})]:
        bad=deepcopy(actual);bad['preparation'][key]=value
        assert compare_output(expected,bad),key
    for key,value in [('float_backend','Ruy'),('observed_replicas',2),('configured_compute_type','float32'),
                      ('ctranslate2_source','4.8.3'),('intra_threads',True),('max_input_length',512)]:
        bad=deepcopy(actual);bad['results'][6]['actual_runtime'][key]=value
        assert compare_output(expected,bad),key
    for value in [False,0,-1,1.5]:
        bad=deepcopy(actual);bad['prepare_ns']=value
        assert compare_output(expected,bad)
    for key,value in [('reported_hwm_bytes',0),('observed_peak_bytes',1),('phase','invented')]:
        bad=deepcopy(actual);bad['memory_samples'][1][key]=value
        assert compare_output(expected,bad),key
    bad=deepcopy(actual);bad['memory_samples'].pop()
    assert compare_output(expected,bad)
    # Kernel VmHWM may decrease; the retained running maximum must remain exact.
    peak=actual['memory_samples'][0]['reported_hwm_bytes']
    for row in actual['memory_samples'][1:]:
        row['reported_hwm_bytes']=max(1,peak//2);row['observed_peak_bytes']=peak
    assert compare_output(expected,actual)==[]


def test_original_replay_requires_frozen_module_runtime_and_all_local_histories():
    _,expected,_=evidence()
    assert compare_reference(expected,deepcopy(expected))==[]
    for key,value in [('platform','Linux'),('cases',[]),('prepared_artifacts',{}),('recipe_sha256','0'*64)]:
        bad=deepcopy(expected);bad[key]=value
        assert compare_reference(expected,bad),key
    for key,value in [('frozen_import',1),('module_hashes',{}),('unicode','16.0.0'),('runtime',{})]:
        bad=deepcopy(expected);bad['oracle'][key]=value
        assert compare_reference(expected,bad),key
    bad=deepcopy(expected);bad['results'][6]['calls'][0]['output']='wrong'
    assert compare_reference(expected,bad)


def test_original_replay_binds_current_verified_manifest_without_freezing_unrelated_checkout_files():
    _,expected,_=evidence()
    current=deepcopy(expected);current['reference_fingerprint']='b'*64
    assert compare_reference(expected,current)
    assert compare_reference(expected,current,reference_fingerprint='b'*64)==[]
    assert compare_reference(expected,current,reference_fingerprint='c'*64)
    current['oracle']['module_hashes']={}
    assert compare_reference(expected,current,reference_fingerprint='b'*64)


def test_platform_oracle_selection_rejects_ambiguous_or_foreign_registered_platforms():
    document,_,_=evidence()
    assert select_oracle(document,'Darwin','arm64')['platform']=='Darwin'
    for system,arch in [('Linux','arm64'),('Darwin','x86_64'),('Windows','aarch64')]:
        with pytest.raises(ValueError):select_oracle(document,system,arch)
    duplicate=deepcopy(document);duplicate['oracles'].append(deepcopy(document['oracles'][0]))
    with pytest.raises(ValueError):select_oracle(duplicate,'Darwin','arm64')


def test_native_dependency_policy_requires_platform_gemm_and_rejects_foreign_or_python_libraries():
    from tools.rust_migration.translation_compare import dependency_errors
    mac='/tmp/probe:\n\t/System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate (compatibility version 1.0.0)\n\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
    linux='linux-vdso.so.1 (0x1)\nlibgomp.so.1 => /lib/aarch64-linux-gnu/libgomp.so.1 (0x1)\nlibstdc++.so.6 => /lib/aarch64-linux-gnu/libstdc++.so.6 (0x1)\nlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x1)\n/lib/ld-linux-aarch64.so.1 (0x1)\n'
    assert dependency_errors(mac,'Darwin')==[]
    assert dependency_errors(linux,'Linux')==[]
    for text,system in [(mac.replace('Accelerate.framework','Other.framework'),'Darwin'),
                        (linux.replace('libgomp.so.1','libomp.so.1'),'Linux'),
                        (mac+'\t/tmp/libpython3.12.dylib (compatibility version 1.0.0)\n','Darwin'),
                        (linux+'libpython3.12.so => /tmp/libpython3.12.so (0x1)\n','Linux'),
                        (linux.replace('/lib/aarch64-linux-gnu/libgomp','/tmp/libgomp'),'Linux')]:
        assert dependency_errors(text,system)
