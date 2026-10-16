"""Regression probes derived from the independent review's synthetic fixtures."""
import json,hashlib
from pathlib import Path
import pytest
import public_default_three_arm_score as score
old=score.old
S=Path(score.__file__)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,sort_keys=True))
def rows(p,objs):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(o,sort_keys=True)+'\n' for o in objs))

def fixture(root,mutation):
 cases=[{'id':'synthetic-a','repo_id':'alpha','target_kind':'symbol','query':'Find the synthetic transformation.','language':'en','query_style':'behavior'}, {'id':'synthetic-b','repo_id':'beta','target_kind':'class','query':'Encuentra el objeto sintético.','language':'es','query_style':'behavior'}]
 public=root/'public.jsonl';rows(public,cases)
 golds=[root/'sealed-labels-a.jsonl',root/'sealed-labels-b.jsonl']
 for p in golds:p.write_text('NEVER READ SYNTHETIC LABEL PAYLOAD\n')
 previous=root/'old-lock.json';plock=root/'prod-lock.json';final=root/'score-lock.json'
 policies={r:{'engine_root':'/synthetic/'+r,'source_receipt':'source-'+r} for r in ['baseline','optimized']}
 prev={'scorer_sha256':sha(old.__file__),'grading_sha256':sha(score.verifiable_grading.__file__),'public_cases':str(public),'queries':len(cases),'input_pins':{str(public):sha(public)},'variants':policies,'reference_pins':{str(p.resolve()):sha(p) for p in golds}}
 write(previous,prev)
 prod={'source_receipt':'source-production','variant_policy':{'default_engine':True,'source_receipt':'source-production'},'public_cases':str(public),'queries':len(cases),'input_pins':{str(public):sha(public)}};write(plock,prod)
 paths={role:root/role for role in ['baseline','optimized','production']}
 for role,path in paths.items():
  closed={}
  for c in cases:
   entity={'kind':'function' if c['target_kind']=='symbol' else 'class','qualname':'synthetic_unit','owner':None,'definition_ordinal':0}
   u={'target_kind':c['target_kind'],'path':'synthetic.py','entity':entity,'module_name':None}
   a={'id':c['id'],'repo_id':c['repo_id'],'target_kind':c['target_kind'],'units':[u],'card':{'unit':u}}
   if role!='production':a|={'native_units':[u],'pool_sha256':'same-opaque-pool'}
   else:a['public_response']={'ok':True,'results':[{'piece_kind':u['target_kind'],'path':u['path'],'entity':entity,'stale':False}]}
   perf={'repo':c['repo_id'],'source_receipt':'source-'+role,'providers':['CPUExecutionProvider'],'heavy_imports':[],'peak_rss_native':100000,'rss_unit':'bytes','server_cpu_total_ms':12,'timings':[{'id':c['id'],'ms':1.5,'cpu_ms':None if role=='production' else 1.0}]}
   rows(path/c['repo_id']/'answers.jsonl',[a]);write(path/c['repo_id']/'performance.json',perf)
   closed[c['repo_id']]={name:sha(path/c['repo_id']/name) for name in ['answers.jsonl','performance.json']}
  if mutation=='old_empty_pins' and role=='baseline':closed['alpha']={}
  if mutation=='old_missing_answers_pin' and role=='optimized':closed['alpha'].pop('answers.jsonl')
  if mutation=='old_missing_performance_pin' and role=='baseline':closed['alpha'].pop('performance.json')
  if mutation=='prod_missing_answers_pin' and role=='production':closed['alpha'].pop('answers.jsonl')
  if mutation=='old_pool_differs' and role=='optimized':
   p=path/'alpha'/'answers.jsonl';a=old.rows(p)[0];a['pool_sha256']='changed';rows(p,[a]);closed['alpha']['answers.jsonl']=sha(p)
  if mutation=='production_pool_may_differ' and role=='production':pass
  if mutation=='incomplete_production' and role=='production':closed.pop('alpha')
  if mutation=='duplicate_production_units' and role=='production':
   p=path/'alpha'/'answers.jsonl';a=old.rows(p)[0];a['units']*=2;a['public_response']['results']*=2;rows(p,[a]);closed['alpha']['answers.jsonl']=sha(p)
  if mutation=='nan_production_timing' and role=='production':
   p=path/'alpha'/'performance.json';perf=json.loads(p.read_text());perf['timings'][0]['ms']=float('nan');write(p,perf);closed['alpha']['performance.json']=sha(p)
  if mutation=='unknown_rss_unit' and role=='production':
   p=path/'alpha'/'performance.json';perf=json.loads(p.read_text());perf['rss_unit']='MB';write(p,perf);closed['alpha']['performance.json']=sha(p)
  if mutation=='extra_empty_repository' and role=='production':
   repo='extraneous';rows(path/repo/'answers.jsonl',[]);write(path/repo/'performance.json',{'repo':repo,'source_receipt':'source-production','providers':['CPUExecutionProvider'],'heavy_imports':[],'peak_rss_native':999999999,'rss_unit':'bytes','server_cpu_total_ms':1234567,'timings':[]});closed[repo]={n:sha(path/repo/n) for n in ['answers.jsonl','performance.json']}
  reg={'status':'ALL additional public outputs closed without Gold','variant':role,'variant_policy':prod['variant_policy'] if role=='production' else policies[role],'lock_sha256':sha(plock if role=='production' else previous),'closed':closed};write(path/'registration.json',reg)
 new={'scorer_sha256':sha(S),'previous_scorer_sha256':sha(old.__file__),'grading_sha256':sha(score.verifiable_grading.__file__),'previous_lock':str(previous),'previous_lock_sha256':sha(previous),'production_lock':str(plock),'production_lock_sha256':sha(plock),'capture_registration_pins':{r:sha(p/'registration.json') for r,p in paths.items()}}
 write(final,new)
 return final,paths,golds

@pytest.mark.parametrize('defect',['old_empty_pins','old_missing_answers_pin','old_missing_performance_pin','prod_missing_answers_pin','old_pool_differs','incomplete_production','duplicate_production_units','nan_production_timing','unknown_rss_unit','extra_empty_repository'])
def test_three_arm_preflight_rejects_defect_without_opening_references(tmp_path,defect,monkeypatch):
    lock,paths,golds=fixture(tmp_path,defect)
    real_rows=old.rows
    def guarded(path):
        if Path(path).resolve() in {p.resolve() for p in golds}:
            raise AssertionError('reference payload opened before public guards')
        return real_rows(path)
    monkeypatch.setattr(old,'rows',guarded)
    with pytest.raises(ValueError):
        score.preflight(lock,paths['baseline'],paths['optimized'],paths['production'])
    assert all(p.read_text()=='NEVER READ SYNTHETIC LABEL PAYLOAD\n' for p in golds)

@pytest.mark.parametrize('variant',['valid','production_pool_may_differ'])
def test_complete_valid_preflight_permits_generic_production_pools(tmp_path,variant):
    lock,paths,golds=fixture(tmp_path,variant)
    result=score.preflight(lock,paths['baseline'],paths['optimized'],paths['production'])
    assert len(result[3])==3
    assert result[-1][-1]['cpu_ms_p50'] is None
