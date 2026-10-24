"""Piece acceptance binds complete outputs, source guards and exact decisions."""
from copy import deepcopy
from pathlib import Path
import gzip,json,math
import pytest
from tools.rust_migration.piece_validate import FORMAT,requests,compare_case,compare_observations
ROOT=Path(__file__).resolve().parents[2]
def reference(family='presentation'):
    suffix='-linux-x86_64'if family in('presentation','cards','evidence','evidence-edges')else'-linux'if family in('ranking-edges','ranking-empty-declaration')else''
    path=ROOT/f'crates/ken-retrieval/tests/fixtures/piece-reference-{family}{suffix}.json'
    value=json.loads(path.read_bytes()if path.exists()else gzip.decompress(path.with_suffix('.json.gz').read_bytes()))
    return dict(value,cases=[dict(c,family=family)for c in value['cases']])
def pair(family='presentation'):
    ref=reference(family)
    expected=next(c for c in ref['cases']if'result'in c)
    return expected,{k:deepcopy(v)for k,v in expected.items()if k!='input'}
def test_complete_source_response_and_calls_match():
    for family in ('catalog','assembly','ranking','cards','evidence','evidence-edges','presentation'):
        a,b=pair(family);assert not compare_case(a,b)
@pytest.mark.parametrize('change',['range','content','owner','hash','order','warning','omission','boolean','characters','extra','kind','id'])
def test_any_public_source_or_diagnostic_drift_rejects(change):
    a,b=pair();response=b['result']['response'];result=response['results'][0]
    if change=='range':result['evidence'][0]['end_line']+=1
    elif change=='content':result['evidence'][0]['content']+=' fabricated'
    elif change=='owner':result['entity']['qualname']='other'
    elif change=='hash':result['source_hash']='0'*64
    elif change=='order':result['evidence'].reverse();result['evidence'].append(deepcopy(result['evidence'][0]))
    elif change=='warning':response['warnings'].append('invented')
    elif change=='omission':response['omitted_count']+=1
    elif change=='boolean':result['stale']=1
    elif change=='characters':b['result']['characters']+=1
    elif change=='extra':b['passed']=True
    elif change=='kind':b['kind']='other'
    else:b['id']='other'
    assert compare_case(a,b)
def test_one_ulp_score_and_noncoverage_features_remain_exact():
    ref=reference('ranking')
    a=next(c for c in ref['cases']if c['kind']=='piece_rank'and c.get('result',{}).get('scores'))
    b={k:deepcopy(v)for k,v in a.items()if k!='input'};b['result']['scores'][0]=math.nextafter(b['result']['scores'][0],math.inf)
    assert compare_case(a,b)
@pytest.mark.parametrize('target',['encoder','stemmer','paths','schema'])
def test_model_calls_schema_and_path_digests_are_binding(target):
    ref=reference('ranking');a=next(c for c in ref['cases']if c.get('encoder_calls')and c.get('stemmer_calls')and'result'in c and(target!='paths'or'paths_sha256'in c['result']))
    b={k:deepcopy(v)for k,v in a.items()if k!='input'}
    if target=='encoder':b['encoder_calls'].pop()
    elif target=='stemmer':b['stemmer_calls'].pop()
    elif target=='schema':b['result'].get('features',b['result'])['names'].reverse()
    else:b['result']['paths_sha256']='0'*64
    assert compare_case(a,b)
def test_only_declared_production_coverage_columns_receive_float_bounds():
    ref=reference('ranking');a=next(c for c in ref['cases']if c['input'].get('production')and c['kind']=='piece_rank')
    b={k:deepcopy(v)for k,v in a.items()if k!='input'};values=b['result']['features']['values'][0]
    column=next(i for i,v in enumerate(values)if i>=30 and type(v)is float and v!=0)
    values[column]+=1e-7
    assert not compare_case(a,b)
    values[0]+=1e-7;assert compare_case(a,b)
def test_requests_are_input_only_and_inventory_order_is_required():
    ref=reference();request=requests(ref,{})
    assert request['format']==FORMAT and all(set(c)=={'id','family','kind','input'}for c in request['cases'])
    assert compare_observations(ref,dict(format=FORMAT,platform='linux',cases=[]))
def test_macos_private_temp_alias_is_portable_without_hiding_diagnostic_or_size_drift():
    ref=reference();base=next(c for c in ref['cases']if c['id']=='owner-current-delete')
    expected=deepcopy(base);actual={k:deepcopy(v)for k,v in base.items()if k!='input'}
    expected['result']['response']['warnings'][0]=expected['result']['response']['warnings'][0].replace('{project}','/private{project}')
    expected['result']['characters']+=len('/private')
    assert not compare_case(expected,actual)
    actual['result']['characters']+=1;assert compare_case(expected,actual)
    actual['result']['characters']-=1;actual['result']['response']['warnings'][0]+=' invented';assert compare_case(expected,actual)

def test_invalid_class_declarations_are_explicit_stronger_identity_guards():
    ref=reference('ranking-edges');cases=[c for c in ref['cases']if c['id'].startswith('edge-declaration-kind-')and c['id']!='edge-declaration-kind-class']
    assert len(cases)==7
    for expected in cases:
        original={k:deepcopy(v)for k,v in expected.items()if k!='input'}
        assert compare_case(expected,original),'unsafe original construction cannot certify current admission'
        actual={k:expected[k]for k in('id','family','kind')}
        actual.update(error=dict(type='ValueError',message='requested piece identity disagrees with its kind'),encoder_calls=[],stemmer_calls=[])
        assert not compare_case(expected,actual)
        actual['encoder_calls']=[dict(op='query',text='unexpected')];assert compare_case(expected,actual)
    valid=next(c for c in ref['cases']if c['id']=='edge-declaration-kind-class')
    assert not compare_case(valid,{k:v for k,v in valid.items()if k!='input'})
