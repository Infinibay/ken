"""A numerically plausible contextual response is insufficient acceptance."""
from copy import deepcopy
import math

import pytest

from tools.rust_migration.context_compare import RUNTIME, compare_output, select_oracle


def test_context_comparison_rejects_wrong_inputs_identity_raw_vectors_and_core():
    core={'os':'linux','arch':'aarch64','version':'1.25.1','api':25,'bytes':10,'sha256':'a'*64}
    expected={'platform':'Linux','architecture':'aarch64','dimension':3,
        'artifacts':{'graph':{'bytes':1,'sha256':'b'*64}},
        'spec':{'revision':'c'*64},'spec_key':'fixed-key','tokenizer_revision':'fixed-tok',
        'cases':[{'id':'empty','prepare':False,'calls':[{'op':'passages'}]},
                 {'id':'one','prepare':True,'calls':[{'op':'tokens'},{'op':'query'},{'op':'passages'}]}],
        'results':[{'id':'empty','calls':[[]],'session_loaded':False,'providers':[]},
                   {'id':'one','calls':[{'ids':[4,1,2,5],'attention_mask':[1]*4},[3.,4.,0.],[[0.,0.,0.],[3.,4.,0.]]],
                    'session_loaded':True,'providers':['CPUExecutionProvider']}]}
    valid={'dimension':3,'artifacts':expected['artifacts'],
        'compatible_identity':{k:expected[k] for k in ['spec','spec_key','tokenizer_revision']},
        'runtime':RUNTIME|{'native_core':core},'prepare_ns':1,'results':deepcopy(expected['results'])}
    for row in valid['results']:
        row.update(load_ns=1,inference_ns=1,peak_after_load_bytes=1,peak_after_inference_bytes=1)
    assert compare_output(expected,valid,core)==[]
    for key,value in [('dimension',4),('artifacts',{}),('compatible_identity',{}),('results',[]),('runtime',{})]:
        assert compare_output(expected,valid|{key:value},core)
    for key,value in [('native_core',core|{'sha256':'0'*64}),('engine','python'),('intra_threads',3)]:
        bad=deepcopy(valid);bad['runtime'][key]=value;assert compare_output(expected,bad,core)
    for index,value in [(0,{'ids':[4,1,2,5],'attention_mask':[1,1,1,0]}),
                        (0,{'ids':[4,True,2,5],'attention_mask':[1]*4}),
                        (0,{'ids':[4,1.,2,5],'attention_mask':[1]*4}),
                        (1,[.6,.8,0]),(1,[math.nan,4.,0]),(1,[math.inf,4.,0]),
                        (1,[3.,4.]),(1,[0,0,0]),(2,[[1e-12,0,0],[3,4,0]]),(2,[])]:
        bad=deepcopy(valid);bad['results'][1]['calls'][index]=value;assert compare_output(expected,bad,core)
    for key,value in [('id','other'),('session_loaded',False),('providers',['CUDAExecutionProvider']),
                      ('peak_after_inference_bytes',0),('calls',[])]:
        bad=deepcopy(valid);bad['results'][1][key]=value;assert compare_output(expected,bad,core)
    bad=deepcopy(valid);bad['results'][0]['session_loaded']=True;assert compare_output(expected,bad,core)
    assert compare_output(expected,[],core)
    bad=deepcopy(expected);bad['results'][1]['calls'][1][0]=math.nan
    assert compare_output(bad,valid,core), 'a corrupted original vector must fail too'


def test_original_platform_selection_never_substitutes_another_architecture():
    original={'platform':'Linux','architecture':'aarch64'}
    document={'platforms':{'Linux/aarch64':original}}
    assert select_oracle(document,'Linux','aarch64')==original
    for system,arch in [('Darwin','arm64'),('Linux','x86_64')]:
        with pytest.raises(ValueError,match='platform'):
            select_oracle(document,system,arch)
    with pytest.raises(ValueError,match='platform'):
        select_oracle({'platforms':{'Darwin/arm64':original}},'Darwin','arm64')
