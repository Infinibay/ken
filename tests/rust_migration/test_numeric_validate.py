"""Complete numeric rows, decisions, diagnostic categories and calls are binding."""
from copy import deepcopy
from pathlib import Path
import json,pytest
from tools.rust_migration.numeric_validate import compare_case,compare_observations,requests,FORMAT
ROOT=Path(__file__).resolve().parents[2]
def pair():
    ref=json.loads((ROOT/'crates/ken-retrieval/tests/fixtures/numeric-reference-owner-ranking.json').read_bytes())
    a=next(c for c in ref['cases']if c['kind']=='rank_trace'and len(c.get('result',{}).get('matches',[]))==2)
    return a,{k:deepcopy(v)for k,v in a.items()if k!='input'}
def test_complete_numeric_snapshot_and_calls_pass():
    a,b=pair();assert not compare_case(a,b)
@pytest.mark.parametrize('change',['names','rows','features','owner','order','evidence','score','boolean','calls','stems','paths','extra','kind'])
def test_any_numeric_schema_owner_order_or_call_drift_rejects(change):
    a,b=pair();t=b['result']['trace']
    if change=='names':t['feature_names'].reverse()
    elif change=='rows':t['owners'].pop()
    elif change=='features':t['owners'][0]['feature_values'][0]+=.1
    elif change=='owner':b['result']['matches'][0]['entity']['qualname']='other'
    elif change=='order':b['result']['matches'].reverse()
    elif change=='evidence':b['result']['matches'][0]['evidence'].pop()
    elif change=='score':b['result']['matches'][0]['score']+=.1
    elif change=='boolean':t['owners'][0]['feature_values'][0]=True
    elif change=='calls':b['encoder_calls'].reverse()
    elif change=='stems':b['stemmer_calls'].pop()
    elif change=='paths':b['result']['pair']['numeric']['trees'][0]['left_path'].append({'branch':'right'})
    elif change=='extra':b['passed']=True
    else:b['kind']='not-ranking'
    assert compare_case(a,b)
def test_request_inventory_contains_only_inputs():
    a,b=pair();r=requests(dict(cases=[dict(a,family='owner-ranking')]),{})
    assert r['format']==FORMAT and set(r['cases'][0])=={'id','family','kind','input'}
    assert compare_observations(dict(cases=[a]),dict(format=FORMAT,cases=[]))

@pytest.mark.parametrize('target',['prediction','ranked-score','trace-score','evidence-signal','explanation'])
def test_one_ulp_drift_in_exact_outcomes_rejects(target):
    import math
    a,b=pair()
    if target=='prediction':
        a=dict(id='exact',family='forest',kind='predict',input={},result=dict(scores=[1.],unchanged=True))
        b={k:deepcopy(v)for k,v in a.items()if k!='input'}
        value=b['result']['scores'];key=0
    elif target=='ranked-score':value=b['result']['matches'][0];key='score'
    elif target=='trace-score':value=b['result']['trace']['owners'][0];key='score'
    elif target=='evidence-signal':value=b['result']['matches'][0]['signals'];key=next(iter(value))
    else:value=b['result']['pair']['numeric'];key='margin'
    if isinstance(value,dict):assert key in value
    value[key]=math.nextafter(value[key],math.inf)
    assert compare_case(a,b),target

@pytest.mark.parametrize('mode',['feature-bound','production-feature-bound','outside-bound','evidence-named-feature_values'])
def test_only_declared_feature_paths_receive_fixed_bounds(mode):
    a,b=pair()
    for c in [a,b]:c['family']='owner-ranking'
    if mode=='evidence-named-feature_values':
        for c in [a,b]:c['result']['matches'][0]['signals']['feature_values']=1.
        b['result']['matches'][0]['signals']['feature_values']+=1e-13
    else:
        if mode=='production-feature-bound':
            for c in [a,b]:c['kind']='production_compose';c['family']='production'
        v=b['result']['trace']['owners'][0]['feature_values']
        v[0]+=1e-7 if mode=='production-feature-bound'else .1 if mode=='outside-bound'else 1e-13
    assert bool(compare_case(a,b))==(mode in('outside-bound','evidence-named-feature_values'))
