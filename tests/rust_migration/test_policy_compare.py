"""Decision mutations must fail exact, typed original/native comparison."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.rust_migration.policy_compare import (
    GOLDEN, RUNTIME, compare_output, compare_reference, dependency_errors, select_oracle,
)


def original():
    return select_oracle(json.loads(GOLDEN.read_text()),'Darwin','arm64')


def native(expected):
    return {'format':'ken-model-policy-native/1','runtime':deepcopy(RUNTIME),
        'results':deepcopy(expected['results']),'prompts':deepcopy(expected['prompts'])}


def test_all_original_policy_decisions_require_exact_fields_order_and_json_types():
    expected=original();valid=native(expected)
    assert compare_output(expected,valid)==[]
    fresh=next(i for i,r in enumerate(valid['results']) if r['project']['initial_pin'])
    upgrade=next(i for i,r in enumerate(valid['results']) if r['upgrade'])
    changes=[
        (['results',0,'recommended'],'wrong'),(['results',0,'project','model'],'wrong'),
        (['results',fresh,'project','initial_pin','model'],'wrong'),
        (['results',fresh,'project','initial_pin','document_space'],2.0),
        (['results',fresh,'project','initial_pin','document_space'],True),
        (['results',upgrade,'upgrade','recommended'],'wrong'),
        (['results',0,'active'],list(reversed(valid['results'][0]['active']))),
        (['prompts',0,'query'],' '),(['prompts',0,'asymmetric'],0),
        (['runtime','model_runtime_needed'],0),(['runtime','model_runtime_needed'],True),
        (['runtime','engine'],'python'),(['runtime','unicode'],'16.0.0'),
    ]
    for path,value in changes:
        bad=deepcopy(valid);owner=bad
        for key in path[:-1]:owner=owner[key]
        owner[path[-1]]=value
        assert compare_output(expected,bad),path
    for change in ['missing','extra','duplicate','reorder','field','root','not-object']:
        bad=deepcopy(valid)
        if change=='missing':bad['results'].pop()
        elif change=='extra':bad['results'].append({'id':'extra'})
        elif change=='duplicate':bad['results'][1]=deepcopy(bad['results'][0])
        elif change=='reorder':bad['results'].reverse()
        elif change=='field':bad['results'][0]['project']['unexpected']=True
        elif change=='root':bad['observations']=[]
        else:bad=[]
        assert compare_output(expected,bad),change


def test_fresh_original_replay_must_preserve_provenance_logical_rows_and_exact_pins():
    expected=original()
    assert compare_reference(expected,deepcopy(expected))==[]
    for path,value in [
        (['oracle','frozen_import'],False),(['oracle','unicode'],'16.0.0'),
        (['oracle','sources'],{}),(['reference_fingerprint'],'0'*64),
        (['platform'],'Linux'),(['architecture'],'x86_64'),
        (['observations',0,'selection_preserves_rows'],False),
        (['observations',0,'encoder_singleton_unloaded'],False),
        (['observations',0,'metadata_after'],{}),(['results'],[]),(['prompts'],[]),
    ]:
        bad=deepcopy(expected);owner=bad
        for key in path[:-1]:owner=owner[key]
        owner[path[-1]]=value
        assert compare_reference(expected,bad),path
    document=json.loads(GOLDEN.read_text())
    with pytest.raises(ValueError):select_oracle(document,'Linux','x86_64')
    document['oracles'].append(deepcopy(document['oracles'][0]))
    with pytest.raises(ValueError):select_oracle(document,'Darwin','arm64')


def test_dependency_audit_rejects_model_runtimes_and_non_system_libraries():
    mac='probe:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1)\n'
    linux='linux-vdso.so.1 (0x1)\nlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x1)\n/lib/ld-linux-aarch64.so.1 (0x1)\n'
    assert dependency_errors(mac,'Darwin')==[]
    assert dependency_errors(linux,'Linux')==[]
    for path in ['/tmp/libpython.dylib','/tmp/libonnxruntime.dylib','/usr/lib/libtorch.dylib']:
        assert dependency_errors(mac+'\t'+path+' (compatibility version 1)\n','Darwin')
    for name in ['libpython3.12.so','libonnxruntime.so','libtorch.so','libunregistered.so']:
        assert dependency_errors(linux+f'{name} => /usr/lib/{name} (0x1)\n','Linux')
    assert dependency_errors(linux.replace('/lib/aarch64-linux-gnu/libc.so.6','/tmp/libc.so.6'),'Linux')
