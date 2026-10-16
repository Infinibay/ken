"""Fresh acceptance guards must fail before any private reference is opened."""
import hashlib,json
from pathlib import Path
import pytest
import fresh_public_piece_score as score

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x))
def rows(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(r)+'\n' for r in x))
def fixture(root,defect='valid'):
 repos=['ajv','attrs','boltons','commons-csv','junit5','marked','packaging','pytest'];kinds=['class','module','symbol','file']
 cases=[{'id':f'fresh-{i:03}','query':f'Find synthetic responsibility {i}.','repo_id':repos[i%8],'target_kind':kinds[i%4],'language':'en' if i%5<3 else 'es','query_style':'behavior' if i%5<4 else 'qualified_lookup'} for i in range(200)]
 if defect=='bad_count':cases.pop()
 if defect=='bad_type_quota':cases[0]['target_kind']='symbol'
 public=root/'public.jsonl';rows(public,cases);gold=root/'PRIVATE.jsonl';gold.write_text('NEVER READ PRIVATE REFERENCES')
 engine=root/'engine';(engine/'src').mkdir(parents=True);(engine/'src/synthetic.py').write_text('value = 1\n');(engine/'pyproject.toml').write_text('[project]\nname="synthetic"\n')
 files={n:sha(engine/n) for n in ['src/synthetic.py','pyproject.toml']};write(engine/'SOURCE-MANIFEST.json',{'files':files,'tree_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()});source_receipt=sha(engine/'SOURCE-MANIFEST.json')
 if defect=='engine_changed':(engine/'src/synthetic.py').write_text('value = 2\n')
 plock=root/'production-lock.json';prod={'queries':200,'public_cases':str(public),'engine_root':str(engine),'source_receipt':source_receipt,'variant_policy':{'engine_root':str(engine),'source_receipt':source_receipt,'default_engine':True},'input_pins':{str(public):sha(public)}};prod['producer_sha256']=sha(Path(score.__file__).with_name('public_default_mcp_run.py'));prod['server_launcher']=str(Path(score.__file__).with_name('public_default_server.py'));prod['input_pins'].update({str(Path(score.__file__).with_name(n)):sha(Path(score.__file__).with_name(n)) for n in ['public_default_mcp_run.py','public_default_server.py']});write(plock,prod)
 capture=root/'capture';closed={}
 for repo in repos:
  batch=[c for c in cases if c['repo_id']==repo];answers=[]
  for c in batch:
   kind=c['target_kind'];entity={'kind':'class' if kind=='class' else 'function','qualname':'synthetic','owner':None,'definition_ordinal':0} if kind in {'class','symbol'} else None
   u={'target_kind':kind,'path':'synthetic.py','entity':entity,'module_name':'synthetic' if kind=='module' else None}
   r={'id':c['id'],'repo_id':repo,'target_kind':kind,'units':[u],'card':{'unit':u},'public_response':{'results':[{'piece_kind':kind,'path':u['path'],'entity':entity or {'kind':kind,'qualname':'synthetic'},'module_name':u['module_name'],'stale':False}]}}
   answers.append(r)
  perf={'repo':repo,'source_receipt':prod['source_receipt'],'providers':['CPUExecutionProvider'],'heavy_imports':[],'rss_unit':'bytes','peak_rss_native':123456,'server_cpu_total_ms':50.,'timings':[{'id':c['id'],'ms':1.,'cpu_ms':None} for c in batch]}
  if repo=='ajv':
   if defect=='nan_ms':perf['timings'][0]['ms']=float('nan')
   if defect=='wrong_kind':answers[0]['target_kind']='file'
   if defect=='duplicate_unit':answers[0]['units']*=2
   if defect=='bad_public_identity':answers[0]['public_response']['results'][0]['path']='other.py'
  rows(capture/repo/'answers.jsonl',answers);write(capture/repo/'performance.json',perf)
  closed[repo]={n:sha(capture/repo/n) for n in ['answers.jsonl','performance.json']}
 if defect=='missing_hash':closed['ajv'].pop('performance.json')
 reg={'status':'ALL additional public outputs closed without Gold','variant':'production','variant_policy':prod['variant_policy'],'lock_sha256':sha(plock),'closed':closed};write(capture/'registration.json',reg)
 lock={'scope':'FRESH_BALANCED200_CANONICAL_PIECE_ACCEPTANCE','production_lock':str(plock),'production_lock_sha256':sha(plock),'capture_registration_sha256':sha(capture/'registration.json'),'reference_pins':{str(gold):sha(gold)},'code_pins':{str(Path(score.source.__file__)):sha(score.source.__file__),str(Path(score.__file__)):sha(score.__file__),str(Path(score.guards.__file__)):sha(score.guards.__file__),str(Path(score.old.__file__)):sha(score.old.__file__),str(Path(score.grading.__file__)):sha(score.grading.__file__)}}
 final=root/'scoring-lock.json';write(final,lock);return final,capture,gold

@pytest.mark.parametrize('defect',['engine_changed','bad_count','bad_type_quota','nan_ms','wrong_kind','duplicate_unit','bad_public_identity','missing_hash'])
def test_rejects_invalid_fresh_capture_before_opening_gold(tmp_path,defect,monkeypatch):
 lock,capture,gold=fixture(tmp_path,defect);opened=[];real=Path.open
 def guarded(path,*a,**kw):
  if path.resolve()==gold.resolve():opened.append(path);raise AssertionError('private payload opened before guards')
  return real(path,*a,**kw)
 monkeypatch.setattr(Path,'open',guarded)
 with pytest.raises(ValueError):score.preflight(lock,capture,protected_paths=[gold])
 assert not opened

def test_valid_fresh_preflight_preserves_all200_without_gold(tmp_path,monkeypatch):
 lock,capture,gold=fixture(tmp_path);real=Path.open
 def guarded(path,*a,**kw):
  assert path.resolve()!=gold.resolve(),'Gold must remain closed during public preflight'
  return real(path,*a,**kw)
 monkeypatch.setattr(Path,'open',guarded)
 result=score.preflight(lock,capture,protected_paths=[gold])
 assert len(result[1])==len(result[2])==200
 assert result[3]['cpu_ms_p50'] is None


def edit_fixture(lock,capture,mutator):
    final=json.loads(lock.read_text());plock=Path(final['production_lock']);prod=json.loads(plock.read_text());reg=json.loads((capture/'registration.json').read_text())
    mutator(prod,reg,final)
    write(plock,prod);reg['lock_sha256']=sha(plock);reg['variant_policy']=prod['variant_policy'];write(capture/'registration.json',reg)
    final['production_lock_sha256']=sha(plock);final['capture_registration_sha256']=sha(capture/'registration.json');write(lock,final)

@pytest.mark.parametrize('defect',['entity_null','wrong_class_kind','missing_ordinal','bool_ordinal','absolute_path','empty_path','null_card','per_kind_language','per_kind_style','truthy_default','wrong_policy_source','missing_producer','missing_launcher'])
def test_review_findings_are_rejected_with_valid_updated_hashes(tmp_path,defect):
    lock,capture,gold=fixture(tmp_path)
    def mutation(prod,reg,final):
        if defect.startswith('per_kind'):
            p=Path(prod['public_cases']);data=[json.loads(x) for x in p.read_text().splitlines()]
            field,first,second=('language','en','es') if defect=='per_kind_language' else ('query_style','behavior','qualified_lookup')
            a=next(c for c in data if c['target_kind']=='class' and c[field]==first);b=next(c for c in data if c['target_kind']=='module' and c[field]==second);a[field],b[field]=b[field],a[field];rows(p,data);prod['input_pins'][str(p)]=sha(p)
        elif defect=='truthy_default':prod['variant_policy']['default_engine']='yes'
        elif defect=='wrong_policy_source':prod['variant_policy']['source_receipt']='other'
        elif defect=='missing_producer':prod.pop('producer_sha256')
        elif defect=='missing_launcher':prod.pop('server_launcher')
        else:
            p=capture/'ajv'/'answers.jsonl';data=[json.loads(x) for x in p.read_text().splitlines()];r=data[0];u=r['units'][0]
            if defect=='entity_null':u['entity']=None;r['public_response']['results'][0]['entity']=None
            elif defect=='wrong_class_kind':u['entity']['kind']='function';r['public_response']['results'][0]['entity']['kind']='function'
            elif defect=='missing_ordinal':u['entity'].pop('definition_ordinal');r['public_response']['results'][0]['entity'].pop('definition_ordinal')
            elif defect=='bool_ordinal':u['entity']['definition_ordinal']=True;r['public_response']['results'][0]['entity']['definition_ordinal']=True
            elif defect in {'absolute_path','empty_path'}:u['path']='/synthetic.py' if defect=='absolute_path' else '';r['public_response']['results'][0]['path']=u['path']
            r['card']=None if defect=='null_card' else {'unit':u};rows(p,data);reg['closed']['ajv']['answers.jsonl']=sha(p)
    edit_fixture(lock,capture,mutation)
    with pytest.raises(ValueError):score.preflight(lock,capture,protected_paths=[gold])

@pytest.mark.parametrize('alias',['lock','production_lock','answers_symlink','answers_hardlink'])
def test_private_aliases_never_attempt_gold_open(tmp_path,alias,monkeypatch):
    lock,capture,gold=fixture(tmp_path)
    if alias=='lock':lock=gold
    elif alias=='production_lock':
        final=json.loads(lock.read_text());final['production_lock']=str(gold);final['production_lock_sha256']=sha(gold);write(lock,final)
    else:
        p=capture/'ajv'/'answers.jsonl';p.unlink()
        if alias=='answers_symlink':p.symlink_to(gold)
        else:p.hardlink_to(gold)
    real=Path.open;attempt=[]
    def guarded(p,*a,**kw):
        if p.resolve()==gold.resolve() or (p.exists() and p.samefile(gold)):attempt.append(p);raise AssertionError('private reference read attempted')
        return real(p,*a,**kw)
    monkeypatch.setattr(Path,'open',guarded)
    with pytest.raises(ValueError):score.preflight(lock,capture,protected_paths=[gold])
    assert not attempt


@pytest.mark.parametrize('defect',['duplicate_module_path','cpu_sum_overflow','wall_median_overflow'])
def test_canonical_duplicates_and_aggregate_overflow_are_rejected(tmp_path,defect):
    import copy
    lock,capture,gold=fixture(tmp_path)
    def mutation(prod,reg,final):
        if defect=='duplicate_module_path':
            p=capture/'attrs'/'answers.jsonl';data=[json.loads(x) for x in p.read_text().splitlines()];r=data[0]
            u=copy.deepcopy(r['units'][0]);u['module_name']='other_name_for_same_physical_module';r['units'].append(u)
            v=copy.deepcopy(r['public_response']['results'][0]);v['module_name']=u['module_name'];r['public_response']['results'].append(v)
            rows(p,data);reg['closed']['attrs']['answers.jsonl']=sha(p)
        else:
            for repo in reg['closed']:
                p=capture/repo/'performance.json';perf=json.loads(p.read_text())
                if defect=='cpu_sum_overflow':perf['server_cpu_total_ms']=1e308
                else:
                    for t in perf['timings']:t['ms']=1e308
                write(p,perf);reg['closed'][repo]['performance.json']=sha(p)
    edit_fixture(lock,capture,mutation)
    with pytest.raises(ValueError):score.preflight(lock,capture,protected_paths=[gold])
