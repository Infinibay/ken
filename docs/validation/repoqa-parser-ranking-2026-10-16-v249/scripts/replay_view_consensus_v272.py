"""Preregistered, model-free view composition diagnostic on two closed languages."""
import hashlib,json,sys
from pathlib import Path
base=Path.cwd();out=base/'output/analysis/repoqa-view-consensus-v272';out.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def key(r):return json.dumps([r['path'],r['entity']],sort_keys=True)
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/src')
from ken.retrieval.symbol_requirements import requirements
from ken.retrieval.model import SearchRequest
runs={'cpp':base/'output/development/repoqa-cpp-coverage-v246','rust':base/'output/analysis/repoqa-rust-stages-v251'}
registrations={}
for language,run in runs.items():
 closure=json.loads((run/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
 for name,digest in closure['response_pins'].items():assert sha(run/'capture'/name)==digest
 registrations[language]={'closure_sha256':sha(run/'capture/closure.json'),'requests_sha256':sha(run/'repoqa-requests.jsonl')}
write(out/'registration.json',{'queries':200,'source_captures':registrations,'policies':{'equal_mean':'existing arithmetic mean, after bitwise correction','code_only':'whole-code logit if eligible; existing atomic original-card fallback otherwise','rrf_context_mean':'equal-weight RRF with fixed existing k=60 of contextual and mean neural order within native10','context_code_agreement':'promote global contextual top eligible symbol only if it is also the best complete-code neural candidate and that complete view was used; otherwise preserve mean order'},'explicit_requirements':'For any existing explicit operation/operator/test requirement, preserve its captured ordering in every arm. Retain all200cases; do not infer new source witnesses from missing data.','reference_labels_in_worker':False,'no_fit':True,'no_neural_inference':True,'reserve':'CLOSED','producer_sha256':sha(Path(__file__))})
rows=[]
for language,run in runs.items():
 requests={r['id']:r for r in map(json.loads,(run/'repoqa-requests.jsonl').read_text().splitlines())}
 for group in sorted({r['repo_id'] for r in requests.values()}):
  inventory=json.loads((run/'capture'/group/'context-owners.json').read_text())
  for stage in json.loads((run/'capture'/group/'stages.json').read_text()):
   request=requests[stage['id']];required=requirements(SearchRequest(request['query'],piece_kind='symbol'))
   assert stage['normal_identities_reproduced'] and 'error' not in stage
   results=stage['diagnostic_response']['results']
   if required.operations or required.operators or required.test_case:
    keep=[{k:r[k] for k in ('path','piece_kind','entity','entity_span','source_hash','stale')} for r in results]
    rows.append({'id':request['id'],'language':language,'explicit_policy_preserved':True,'orders':{name:keep for name in ('equal_mean','code_only','rrf_context_mean','context_code_agreement')}})
    continue
   pieces=sorted(results,key=lambda r:r['signals']['piece_rank']);lookup={key(r):i for i,r in enumerate(inventory)}
   context=[max(stage['contextual_original'][lookup[key(r)]],stage['contextual_expanded'][lookup[key(r)]]) for r in pieces]
   context_order=sorted(range(len(pieces)),key=lambda i:-context[i]);context_rank={i:r for r,i in enumerate(context_order,1)}
   mean_order=sorted(range(len(pieces)),key=lambda i:-pieces[i]['signals']['symbol_ranking']['mean_score']);mean_rank={i:r for r,i in enumerate(mean_order,1)}
   code_order=sorted(mean_order,key=lambda i:-pieces[i]['signals']['symbol_ranking']['code_score'])
   rrf_order=sorted(mean_order,key=lambda i:-(1/(60+context_rank[i])+1/(60+mean_rank[i])))
   eligible=[i for i,v in enumerate(inventory) if v['entity']['kind'] in {'function','method','constructor','destructor','const','constant'}]
   global_first=max(eligible,key=lambda i:max(stage['contextual_original'][i],stage['contextual_expanded'][i]))
   agreement_order=list(mean_order);chosen=code_order[0]
   if key(pieces[chosen])==key(inventory[global_first]) and pieces[chosen]['signals']['symbol_ranking']['code_view_used']:
    agreement_order.remove(chosen);agreement_order.insert(0,chosen)
   orders={'equal_mean':mean_order,'code_only':code_order,'rrf_context_mean':rrf_order,'context_code_agreement':agreement_order}
   assert all(sorted(order)==list(range(len(pieces))) for order in orders.values())
   rows.append({'id':request['id'],'language':language,'orders':{name:[{k:pieces[i][k] for k in ('path','piece_kind','entity','entity_span','source_hash','stale')} for i in order] for name,order in orders.items()}})
assert len(rows)==200 and len({r['id'] for r in rows})==200
write(out/'predictions.json',rows);write(out/'closure.json',{'queries':200,'all_outputs_closed':True,'pins':{p.name:sha(p) for p in out.iterdir() if p.is_file()},'reserve':'CLOSED','reference_labels_used':False})
print(json.dumps({'closed':len(rows),'out':str(out),'no_fit':True}))
