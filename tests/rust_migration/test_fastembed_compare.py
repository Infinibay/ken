"""Synthetic comparator mutations never certify native execution."""
from copy import deepcopy
from pathlib import Path
import gzip,json,struct

import pytest
from tools.rust_migration.fastembed_compare import (
    compare_model,coverage_errors,fingerprint,native_producer,provenance_errors,
)

ROOT=Path(__file__).resolve().parents[2]
CATALOG=json.loads((ROOT/'crates/ken-models/resources/fastembed-catalog.json').read_text())
CASES=json.loads((ROOT/'docs/validation/rust-migration-2026-10-20/m2-fastembed/cases.json').read_text())
CORE=json.loads((ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_text())['libraries'][0]


def fixture():
    definition=CATALOG['models'][4];cases=[c for c in CASES if c['model']==definition['name']]
    original=json.loads(gzip.decompress((ROOT/'docs/validation/rust-migration-2026-10-20/m2-fastembed/reference-macos/04.json.gz').read_bytes()))
    producer=native_producer();frames=[]
    def state(value):return dict(value,dim=definition['dimension'])
    def frame(id,operation,before,after,result):
        loaded=after['model_loaded']
        return {'format':'ken-fastembed-frame/1','id':id,'operation':operation,'model':definition['name'],
            'producer':producer,'model_fingerprint':fingerprint(definition),'assets_fingerprint':fingerprint(definition['assets']),
            'constructor_ns':1,'before':state(before),'state':state(after),'elapsed_ns':1,
            'memory':{key:{'reported_hwm_bytes':12_000_000,'observed_peak_bytes':12_000_000}for key in ['before','after']},
            'preparation':{'device':after['device'],'configured_providers':['CPUExecutionProvider']if loaded else[],
                'attempts':[{'providers':['CPUExecutionProvider'],'error':None}]if loaded else[],
                'runtime':CORE if loaded else None,'model_fingerprint':fingerprint(definition),
                'declared_artifacts_fingerprint':fingerprint(definition['assets']),
                'verified_artifacts_fingerprint':fingerprint(definition['assets'])if loaded else None,
                'notices':definition['advisories']},'result':result}
    before=original['results'][0]['before'];frames.append(frame(definition['name']+':control-cold','status',before,before,{'prepared':False}))
    for result in original['results']:
        batches=[{'inputs':{name:{'shape':tensor['shape'],'values':tensor['values']}for name,tensor in batch['inputs'].items()},'output_shape':batch['outputs'][0]['shape'],'output_dtype':batch['outputs'][0]['dtype']}for batch in result['batches']]
        frames.append(frame(result['id'],'embed',result['before'],result['state'],{key:result[key]for key in ['shape','vectors_f32le_hex']}|{'batches':batches}))
    after=original['results'][-1]['state'];frames.append(frame(definition['name']+':control-final','status',after,after,{'prepared':True}))
    return definition,cases,original,frames,producer


def test_all_case_coverage_and_valid_same_platform_fixture():
    definition,cases,original,frames,producer=fixture()
    assert compare_model(definition,cases,original,frames,producer,CORE)==[]
    assert coverage_errors(CATALOG,CASES,[m['name']for m in CATALOG['models']])==[]
    assert coverage_errors(CATALOG,CASES[:-1],[m['name']for m in CATALOG['models']])
    assert coverage_errors(CATALOG,CASES,[m['name']for m in CATALOG['models']][:-1])
    assert coverage_errors(CATALOG,list(reversed(CASES)),[m['name']for m in CATALOG['models']])


@pytest.mark.parametrize('change',['id','order','token','mask','input_type','shape','output_type','extra_row','vector','nan','dim','model','revision','producer','source','missing'])
def test_native_mutations_reject_false_success(change):
    definition,cases,original,frames,producer=fixture();frames=deepcopy(frames);row=frames[2]
    if change=='id':row['id']='wrong'
    elif change=='order':frames[2],frames[3]=frames[3],frames[2]
    elif change=='token':row['result']['batches'][0]['inputs']['input_ids']['values'][0]+=1
    elif change=='mask':row['result']['batches'][0]['inputs']['attention_mask']['values'][0]^=1
    elif change=='input_type':row['result']['batches'][0]['inputs']['input_ids']['values'][0]=1.0
    elif change=='shape':row['result']['batches'][0]['output_shape'][-1]+=1
    elif change=='output_type':row['result']['batches'][0]['output_dtype']='float16'
    elif change=='extra_row':row['result']['batches'][0]['output_shape'][0]+=1
    elif change=='vector':row['result']['vectors_f32le_hex']=struct.pack('<f',123.).hex()+row['result']['vectors_f32le_hex'][8:]
    elif change=='nan':row['result']['vectors_f32le_hex']=struct.pack('<f',float('nan')).hex()+row['result']['vectors_f32le_hex'][8:]
    elif change=='dim':row['state']['dim']=384+1
    elif change=='model':row['model']='another/model'
    elif change=='revision':row['assets_fingerprint']='0'*64
    elif change=='producer':row['producer']['engine']='python'
    elif change=='source':row['producer']['source_sha256']='0'*64
    elif change=='missing':frames.pop(2)
    assert compare_model(definition,cases,original,frames,producer,CORE),change


def test_stale_binary_source_or_oracle_provenance_cannot_be_resealed():
    expected={'native_sha256':'1'*64,'registry_sha256':'2'*64,'cases_sha256':'3'*64,'oracle_sha256':'4'*64,'producer':native_producer()}
    assert provenance_errors(expected,deepcopy(expected))==[]
    for key in expected:
        bad=deepcopy(expected);bad[key]='0'*64
        assert provenance_errors(expected,bad),key


def test_prepared_paths_are_typed_explicit_and_absolute():
    from tools.rust_migration.preparation import PreparedNativeFastEmbed
    prepared=PreparedNativeFastEmbed(Path('/probe'),Path('/sources'),Path('/registry'))
    assert prepared.environment()=={'KEN_FASTEMBED_PROBE':'/probe','KEN_FASTEMBED_SOURCES':'/sources','KEN_FASTEMBED_REGISTRY':'/registry'}
    for value in [Path('relative'),'not-a-Path']:
        with pytest.raises(ValueError):PreparedNativeFastEmbed(value,Path('/sources'),Path('/registry')).environment()


def test_asset_fingerprint_keeps_accepted_python_default_json_separators():
    declaration={'model_id':'test/static','revision':'1'*40,'license':'Español 🙂','artifacts':{'weights.bin':{'bytes':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}}}
    assert fingerprint(declaration)=='11995e883b97430e0b4f0d20c736d9298afc20ec83bbb603a0429fdcd1f9ceed'
