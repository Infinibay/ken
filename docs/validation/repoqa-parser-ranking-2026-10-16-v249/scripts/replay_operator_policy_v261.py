"""Isolated deterministic final-policy replay; never invokes a relevance model."""
from pathlib import Path
import dataclasses,hashlib,importlib.util,json,shutil,sys
base=Path.cwd();run=base/'output/development/repoqa-cpp-coverage-v246';out=base/'output/analysis/repoqa-bitwise-replay-v261';clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
def identity(v):return json.dumps([v['path'],v['entity']],sort_keys=True)
out.mkdir(exist_ok=False);policy=out/'symbol_requirements.py';shutil.copy2(clean/'src/ken/retrieval/symbol_requirements.py',policy)
closure=json.loads((run/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['response_pins'].items():assert sha(run/'capture'/name)==digest
engine=Path(json.loads((run/'registration.json').read_text())['engine']);sys.path.insert(0,str(engine/'src'))
from ken.retrieval.symbol_requirements import requirements as old_requirements, prefer_operations
from ken.retrieval.model import SearchRequest
from ken.retrieval.public import render
from ken.retrieval.intent import requested_piece_path
spec=importlib.util.spec_from_file_location('replayed_requirements_v258',policy);new=importlib.util.module_from_spec(spec);sys.modules[spec.name]=new;spec.loader.exec_module(new)
requests=[json.loads(x) for x in (run/'repoqa-requests.jsonl').read_text().splitlines()];sources=json.loads((run/'repoqa-sources.json').read_text())
write(out/'registration.json',{'queries':100,'normal_api':False,'deterministic_policy_replay':True,'no_model_inference':True,'source_capture_closure_sha256':sha(run/'capture/closure.json'),'source_engine_manifest_sha256':sha(engine/'SOURCE-MANIFEST.json'),'new_policy_sha256':sha(policy),'producer_sha256':sha(Path(__file__)),'references_in_worker':False,'reserve':'CLOSED','new_runtime_not_measured':True})
observations=[];responses=[]
for group in sorted(sources):
 folder=run/'capture'/group;stages={r['id']:r for r in json.loads((folder/'stages.json').read_text())}
 for response in json.loads((folder/'responses.json').read_text()):
  public=next(r for r in requests if r['id']==response['id']);request=SearchRequest(public['query'],target='symbol',piece_kind='symbol',limit=10,max_chars=12000)
  before,after=old_requirements(request),new.requirements(request);s=stages[public['id']];assert s['normal_identities_reproduced'] and 'error' not in s
  result={k:v for k,v in response.items() if k not in ('elapsed_ms','cpu_ms','compact')}
  if dataclasses.asdict(before)!=dataclasses.asdict(after):
   assert before.operations==after.operations and before.test_case==after.test_case and not after.test_case
   assert before.operators and not after.operators and requested_piece_path(request) is None
   pieces=sorted(s['diagnostic_response']['results'],key=lambda r:r['signals']['piece_rank'])
   order=sorted(range(len(pieces)),key=lambda i:-pieces[i]['signals']['symbol_ranking']['mean_score'])
   witnesses=[r['signals']['symbol_ranking']['source_operations'] for r in pieces]
   order=prefer_operations(after.operations,witnesses,order)
   assert new.prefer_explicit_code_terms(request.query,['']*len(pieces),order)==order
   lookup={identity(r):r for r in response['results']};result['results']=[lookup[identity(pieces[i])] for i in order]
  result['compact']=render(result);responses.append(result)
  observations.append({'id':public['id'],'changed_requirements':dataclasses.asdict(before)!=dataclasses.asdict(after),'before_operators':sorted(before.operators),'after_operators':sorted(after.operators),'old_order':[identity(r) for r in response['results']],'new_order':[identity(r) for r in result['results']]})
assert len(responses)==100 and sorted(r['id'] for r in responses)==sorted(r['id'] for r in requests)
old_checks=[]
for cohort in ('original','symbols'):
 historical=base/f'output/development/public-bounded-symbol-ranking-v214-{cohort}'
 lock=json.loads((historical/'lock.json').read_text());registration=json.loads((historical/'capture/registration.json').read_text());assert sha(historical/'lock.json')==registration['lock_sha256']
 count=0;changed=[]
 for group,pins in registration['closed'].items():
  path=historical/'capture'/group/'answers.jsonl';assert sha(path)==pins['answers.jsonl']
  for row in map(json.loads,path.read_text().splitlines()):
   query=row['public_response']['query'];count+=1
   if dataclasses.asdict(old_requirements(SearchRequest(query)))!=dataclasses.asdict(new.requirements(SearchRequest(query))):changed.append(row['id'])
 assert count==200;old_checks.append({'cohort':cohort,'queries':count,'changed_requirements':changed,'capture_registration_sha256':sha(historical/'capture/registration.json')})
write(out/'responses.json',responses);write(out/'observations.json',observations);write(out/'old400-input-guard-check.json',old_checks)
assert not any(name in sys.modules for name in ('torch','transformers'))
write(out/'closure.json',{'queries':100,'all_outputs_closed':True,'pins':{p.name:sha(p) for p in out.iterdir() if p.is_file()},'reference_labels_used':False,'no_model_inference':True,'reserve':'CLOSED'})
print(json.dumps({'closed':100,'requirements_changed':sum(o['changed_requirements'] for o in observations),'order_changed':sum(o['old_order']!=o['new_order'] for o in observations),'old400_input_checks':old_checks},indent=2))
