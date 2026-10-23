"""Unit tests for strict data/order and predefined numeric-bound comparisons."""
from copy import deepcopy
import pytest
from tools.rust_migration.retrieval_reference import candidate
from tools.rust_migration.retrieval_validate import compare_case

def pair():
    first=candidate('first',cosine_behavior=.5);second=candidate('second',4,cosine_behavior=.4)
    p=deepcopy(first['passages'][0]);p['span']={'start_line':4,'end_line':6};first['passages'].append(p)
    a=dict(id='synthetic',kind='dense',input={},result=[first,second]);b={k:deepcopy(v)for k,v in a.items()if k!='input'};return a,b

def test_complete_result_and_predefined_rounding_bound_pass():
    a,b=pair();assert not compare_case(a,b)
    b['result'][0]['signals']['cosine_behavior']+=1e-7;assert not compare_case(a,b)

def test_original_zero_division_is_an_explicit_native_failure():
    original=dict(id='division',kind='bm25f',error=dict(type='ZeroDivisionError',message='float division by zero'))
    native=dict(id='division',kind='bm25f',error=dict(kind='invalid',message='float division by zero'))
    assert not compare_case(original,native)
    assert compare_case(original,dict(id='division',kind='bm25f',result={'float':'nan'}))

@pytest.mark.parametrize('mutation',['owner','order','evidence','score','bool','extra','regions','kind'])
def test_changed_data_order_or_excessive_rounding_rejects(mutation):
    a,b=pair()
    if mutation=='owner':b['result'][0]['entity']['definition_ordinal']=True
    elif mutation=='order':b['result'].reverse()
    elif mutation=='evidence':b['result'][0]['passages'].reverse()
    elif mutation=='score':b['result'][0]['signals']['cosine_behavior']+=.001
    elif mutation=='bool':b['result'][0]['signals']['cosine_behavior']=True
    elif mutation=='regions':b['result'][0]['owned_regions']=[]
    elif mutation=='kind':b['kind']='fusion'
    else:b['passed']=True
    assert compare_case(a,b)
