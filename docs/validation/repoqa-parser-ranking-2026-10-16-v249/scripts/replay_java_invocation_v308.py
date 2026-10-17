"""Replay the new primitive on all95closed current Java responses, no labels/models."""
from pathlib import Path
import hashlib,importlib.util,json,sys
base=Path.cwd();clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');sys.path.insert(0,str(clean/'src'));sys.path.insert(0,str(clean/'experiments/search-engine'))
from grade_public_v224 import load_closed_results
from ken.retrieval.candidates import owner_passages
from ken.retrieval.connections import project_connection
from ken.retrieval.model import EntityKey,SearchRequest
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.source_operations import OperationWitnesses
from ken.retrieval.symbol_requirements import requirements,prefer_operations
from ken.retrieval.intent import requested_piece_path
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();run=base/'output/development/prior-java-regression-v276';out=base/'output/analysis/prior-java-invocation-v308';out.mkdir(exist_ok=False);requests=[json.loads(x) for x in (run/'repoqa-requests.jsonl').read_text().splitlines()];answers=load_closed_results(run/'capture',[r['id'] for r in requests]);assert len(answers)==95;original_reg=json.loads((run/'registration.json').read_text());assert sha(run/'repoqa-requests.jsonl')==original_reg['requests_sha256'];sources=json.loads((run/'repoqa-sources.json').read_text());old_path=base/'output/frozen/repoqa-final-cpp-v296/src/ken/retrieval/symbol_requirements.py';spec=importlib.util.spec_from_file_location('legacy_v308',old_path);old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
protocol={'queries':95,'capture_closure_sha256':sha(run/'capture/closure.json'),'requests_sha256':sha(run/'repoqa-requests.jsonl'),'before_policy_sha256':sha(old_path),'policy_source_pins':{p.name:sha(p) for p in (clean/'src/ken/retrieval').glob('*.py') if p.name in ('symbol_requirements.py','source_operations.py','symbol_ranking.py')},'producer_sha256':sha(Path(__file__)),'no_model_inference':True,'reserve':'CLOSED','status':'Registered before all95identity orders and exposed references','preconditions':'Changed symbol queries must have no previous operations/test/operator/path preferences and no exact bypass. Therefore their closed final order is their actual mean-logit order. Abort whole replay on unsupported mixing; never drop a request. Verify every observed owner against original CI and closed current source extent/hash.'};(out/'registration.json').write_text(json.dumps(protocol,indent=2)+'\n');predictions=[]
for group in sorted(sources):
 selected=[r for r in requests if r['repo_id']==group];affected=[]
 for r in selected:
  request=SearchRequest(r['query'],target='symbol',piece_kind=r['piece_kind']);a,b=old.requirements(request),requirements(request)
  if r['piece_kind']=='symbol' and a.operations!=b.operations and answers[r['id']]['profile_version']!='best-exact-source-v1':
   assert b.operations==a.operations|{'invocation'} and not a.operations and not a.test_case and not a.operators and requested_piece_path(request) is None,(r['id'],'mixed preference unsupported');affected.append(r)
 paths={item['path'] for r in affected for item in answers[r['id']]['results']};catalog=None
 if paths:
  with project_connection(Path(sources[group]['original_root'])) as conn:
   conn.execute('PRAGMA query_only=ON');catalog=SourceCatalog(Path(selected[0]['root']),{k:v for k,v in owner_passages(conn).items() if k.path in paths})
  observations=OperationWitnesses(catalog)
 for r in selected:
  response=answers[r['id']];before=response['results'];after=before;witnesses=[]
  if r in affected:
   assert catalog is not None
   for item in before:
    key=EntityKey(path=item['path'],**item['entity']);assert catalog.extent(key)==(item['entity_span']['start_line'],item['entity_span']['end_line']) and catalog.hashes[item['path']]==item['source_hash']==sources[group]['source_pins'][item['path']];witnesses.append(observations.for_owner(key))
   indices=prefer_operations(requirements(SearchRequest(r['query'])).operations,witnesses,list(range(len(before))));after=[before[i] for i in indices]
  unit=lambda x:{'target_kind':x['piece_kind'],'path':x['path'],'entity':x['entity'] if x['piece_kind'] in ('symbol','class') else None,'module_name':x.get('module_name') if x['piece_kind']=='module' else None}
  assert sorted(json.dumps(unit(x),sort_keys=True) for x in before)==sorted(json.dumps(unit(x),sort_keys=True) for x in after)
  predictions.append({k:r[k] for k in ('id','repo_id','cohort','language','piece_kind')}|{'orders':{'before':[unit(x) for x in before],'invocation':[unit(x) for x in after]},'changed_input':r in affected,'observed_operations':[sorted(x) for x in witnesses],'source_hashes':[x['source_hash'] for x in before]})
assert len(predictions)==95 and len({r['id'] for r in predictions})==95;(out/'predictions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in predictions));protocol.update(status='ALL95current Java identity orders CLOSED before exposed references',predictions_sha256=sha(out/'predictions.jsonl'));(out/'registration.json').write_text(json.dumps(protocol,indent=2)+'\n');print(json.dumps({'closed':95,'changed_inputs':sum(r['changed_input'] for r in predictions),'changed_orders':sum(r['orders']['before']!=r['orders']['invocation'] for r in predictions),'no_inference':True}))
