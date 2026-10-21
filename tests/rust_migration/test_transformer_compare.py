"""Semantic comparison rejects false raw observations."""
from pathlib import Path
import copy,gzip,json,struct,hashlib
import pytest
from tools.rust_migration.transformer_compare import compare_transformer
from tools.rust_migration.transformer_reference import CATALOG

def observations():
 original=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/transformer-judge.json.gz').read_bytes()))
 capture=original['capture'];rows=[]
 definition=next(m for m in json.loads(CATALOG.read_text())['models'] if m['name']==capture['settings']['model_id'])
 core=next(c for c in json.loads((Path(__file__).resolve().parents[2]/'tools/rust_migration/data/transformer-cores.json').read_text())['cores'] if c['os']=='macos' and c['backend']=='torch')
 for request,result in zip(capture['requests'],capture['results'],strict=True):
  trace={'device':{'kind':'cpu'},'dtype':'float32','core_version':'2.9.0','model_fingerprint':hashlib.sha256(json.dumps(definition['assets'],sort_keys=True).encode()).hexdigest(),'runtime':{'backend':'torch','arch':'aarch64','os':'macos','declared_core_version':'2.9.0','module':{'bytes':4,'sha256':'b'*64},'libraries':core['libraries']}}
  row={'id':request['id'],'preparation':trace,'passed_original_call':result['passed_original_call']}
  if result['passed_original_call']:
   row.update(scores=[v[0] for v in struct.iter_unpack('<f',bytes.fromhex(result['scores_f32le_hex']))],feeds=[f['inputs'] for f in capture['feeds'][slice(*result['feed_range'])]],projection_ids=[9693,2152],remaining=request['remaining'],query_ids=request['query_ids'])
  else:row.update(exception=result['exception'],message=result['message'])
  rows.append(row)
 return original,copy.deepcopy({'format':'ken-relevance-probe/1','initial_preparation':None,'preparation':rows[-1]['preparation'],'rows':rows})

def test_exact_raw_judge_observations_replay_without_normalization():
 original,actual=observations();report=compare_transformer(original,actual)
 assert report['passed'] and report['errors']==[] and report['scores']==43 and report['maximum_absolute_error']==0

@pytest.mark.parametrize('change',['score','nan','tokens','mask','projection','query','budget','device','dtype','exception','message','missing','order','lazy'])
def test_false_scores_tokens_order_state_and_missing_cases_fail_even_with_valid_json(change):
 original,actual=observations();row=actual['rows'][1]
 if change=='score':row['scores'][0]+=0.01
 elif change=='nan':row['scores'][0]=float('nan')
 elif change=='tokens':row['feeds'][0]['input_ids'][0][0]+=1
 elif change=='mask':row['feeds'][0]['attention_mask'][0][0]=0
 elif change=='projection':row['projection_ids'].reverse()
 elif change=='query':row['query_ids']=[99]
 elif change=='budget':row['remaining']+=1
 elif change=='device':row['preparation']=copy.deepcopy(row['preparation']);row['preparation']['device']={'kind':'mps'}
 elif change=='dtype':row['preparation']=copy.deepcopy(row['preparation']);row['preparation']['dtype']='float16'
 elif change=='exception':actual['rows'][0]['exception']='RuntimeError'
 elif change=='message':actual['rows'][0]['message']='other'
 elif change=='missing':actual['rows'].pop()
 elif change=='order':actual['rows'][1:3]=actual['rows'][1:3][::-1]
 else:actual['initial_preparation']={}
 assert not compare_transformer(original,actual)['passed']


def test_real_mlx_capture_uses_registered_dimension_when_original_has_no_dimension_field():
 fixtures=Path(__file__).parent/'fixtures'
 original=json.loads(gzip.decompress((fixtures/'transformer-mlx-original.json.gz').read_bytes()))
 actual=json.loads(gzip.decompress((fixtures/'transformer-mlx-actual.json.gz').read_bytes()))
 assert 'dimension' not in original['capture'] and actual['dimension']==1024
 assert compare_transformer(original,actual)['passed']


def test_missing_preparation_cannot_launch_a_native_profile(tmp_path,monkeypatch):
 from tools.rust_migration.preparation import PreparedNativeTransformer
 from tools.rust_migration import transformer_process
 from tools.rust_migration.transformer_compare import compare_prepared_transformer
 monkeypatch.setattr(transformer_process,'run_transformer',lambda *a,**kw:pytest.fail('missing preparation must not launch'))
 prepared=PreparedNativeTransformer(*(tmp_path/p for p in ('probe','sources','catalog','module','core','runtimes')))
 original,_=observations()
 with pytest.raises((OSError,ValueError)):
  compare_prepared_transformer(prepared,original,Path(__file__).resolve().parents[2],tmp_path/'out')


def test_false_model_asset_fingerprint_in_actual_preparation_is_rejected():
 original,actual=observations();actual['rows'][1]['preparation']['model_fingerprint']='d'*64
 assert not compare_transformer(original,actual)['passed']
