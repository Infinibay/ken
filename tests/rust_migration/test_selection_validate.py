"""The selection comparator checks complete data, traces and fixed numeric bounds."""
from copy import deepcopy
import pytest
from tools.rust_migration.native_json import load
from tools.rust_migration.selection_validate import compare_case,compare_observations,requests,FORMAT
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def pair():
    family=load(ROOT/'crates/ken-retrieval/tests/fixtures/search-selection-reference.json')['families']['context_selection']
    original=next(c for c in family['cases']if 'result'in c)
    actual={k:deepcopy(v)for k,v in original.items()if k!='input'}
    return original,actual

def test_complete_selection_data_and_fixed_rounding_bound_pass():
    a,b=pair();assert not compare_case(a,b)
    b['result']['candidates'][0]['signals']['cosine_code_original']+=1e-7
    assert not compare_case(a,b)

@pytest.mark.parametrize('change',['owner','order','evidence','score','boolean','calls','regions','extra','kind'])
def test_complete_data_or_call_changes_reject(change):
    a,b=pair();c=b['result']['candidates'][0]
    if change=='owner':c['entity']['qualname']='other'
    elif change=='order':b['result']['candidates'].reverse()
    elif change=='evidence':c['passages'].pop()
    elif change=='score':c['signals']['cosine_code_original']+=.01
    elif change=='boolean':c['signals']['cosine_code_original']=True
    elif change=='calls':b['result']['query_calls'].reverse()
    elif change=='regions':c['owned_regions']=[]
    elif change=='extra':b['passed']=True
    else:b['kind']='rank'
    assert compare_case(a,b)

def test_failed_selection_still_authenticates_model_call_order():
    a=dict(id='bad',kind='context',error=dict(type='ValueError',message='bad vector'),query_calls=['original'])
    b=dict(id='bad',kind='context',error=dict(kind='invalid',message='bad vector'),query_calls=['original'])
    assert not compare_case(a,b)
    b['query_calls']=[];assert compare_case(a,b)

def test_requests_are_input_only_and_complete_observation_inventory_is_required():
    a,b=pair();ref=dict(cases=[a],legacy_runtime={})
    request=requests(ref);assert request['format']==FORMAT
    assert set(request['cases'][0])=={'id','kind','input'}
    assert compare_observations(ref,dict(format=FORMAT,cases=[]))
