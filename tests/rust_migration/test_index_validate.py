"""Synthetic semantic tampering is never accepted as execution evidence."""
import copy
import pytest
from tools.rust_migration.index_validate import compare_case
TABLES=['ci_files','ci_symbols','ci_imports','ci_intent_sources','ci_name_tokens','ci_passages','ci_passage_terms','ci_passage_lengths','ci_retrieval_files','ci_retrieval_embeddings','ci_passage_vectors','ci_vec_alloc','ci_vec_free','meta']
def sample():
    snapshot=dict(tables={k:[]for k in TABLES},legacy_vectors={k:[]for k in('ci_files','ci_symbols','ci_intent_sources')},loaded={'passages':[]})
    snapshot['tables']['ci_files']=[[1,'a.py','python',{'blob_hex':'00'},10,1,None,None,0,0]]
    snapshot['legacy_vectors']['ci_files']=[dict(id=1,slot=None,value={'vector':None})]
    result=dict(stats=dict(parsed=1,elapsed_s=0.1),events=[['a.py','indexed']],encoder_calls=[],encoder_loads=0,storage_fallback=False)
    original=dict(id='synthetic',steps=[dict(result=result,snapshot=snapshot)])
    native=copy.deepcopy(original);native['steps'][0]['result']['warnings']=[];native['steps'][0]['result']['stats']['elapsed_s']=0.2
    return original,native,dict(id='synthetic',operations=[dict(op='index',paths=['a.py'])])
def test_declared_timing_changes_preserve_complete_semantics():
    original,native,definition=sample();assert compare_case(original,native,definition)==[]
@pytest.mark.parametrize('mutation',['stat','progress','source','calls','loaded','missing_step','slot','generation','warning'])
def test_changed_results_and_side_effects_reject(mutation):
    original,native,definition=sample();step=native['steps'][0]
    if mutation=='stat':step['result']['stats']['parsed']=0
    elif mutation=='progress':step['result']['events']=[['a.py','unchanged']]
    elif mutation=='source':step['snapshot']['tables']['ci_files'][0][3]={'blob_hex':'ff'}
    elif mutation=='calls':step['result']['encoder_calls']=[['injected']]
    elif mutation=='loaded':step['snapshot']['loaded']['passages']=[[1,{}]]
    elif mutation=='missing_step':native['steps']=[]
    elif mutation=='slot':step['snapshot']['tables']['ci_files'][0][7]=42
    elif mutation=='generation':step['snapshot']['tables']['meta']=[['retrieval_generation','2']]
    else:step['result']['warnings']=['unexplained warning']
    assert compare_case(original,native,definition)
def test_exception_category_and_reason_remain_checked():
    original,native,definition=sample();original['steps'][0].pop('result');original['steps'][0].update(error={'type':'IndexVersionError','message':'source changed'},events=[],encoder_calls=[],encoder_loads=0);native['steps'][0].pop('result');native['steps'][0].update(error={'kind':'index_version','message':'source changed while encoding'},events=[],encoder_calls=[],encoder_loads=0,warnings=[])
    assert compare_case(original,native,definition)==[]
    native['steps'][0]['error']['kind']='invalid';assert compare_case(original,native,definition)
