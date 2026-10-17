"""Retain every numeric feature for closed wrong-first pairs, without source excerpts."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from public_benchmarks_v222 import repoqa_correct_piece
base=Path.cwd();rows=[];names=None;model=None;closure_pins={}
key=lambda r:json.dumps([r['path'],r['entity']],sort_keys=True)
for language,run_name,ledger_name in [('cpp','output/development/repoqa-cpp-coverage-v246','cpp-stage-ledger-v257.json'),('rust','output/analysis/repoqa-rust-stages-v251','rust-stage-ledger-v266.json')]:
 run=base/run_name;closure=json.loads((run/'capture/closure.json').read_text());assert closure['all_outputs_closed'];closure_pins[str(run/'capture/closure.json')]=hashlib.sha256((run/'capture/closure.json').read_bytes()).hexdigest()
 for name,digest in closure['response_pins'].items():assert hashlib.sha256((run/'capture'/name).read_bytes()).hexdigest()==digest
 ledger=json.loads((base/'output/analysis/repoqa-diagnosis-v236'/ledger_name).read_text());grades={r['id']:r for r in ledger['rows']}
 for group in sorted({r['repo_id'] for r in grades.values()}):
  inventory=json.loads((run/'capture'/group/'context-owners.json').read_text())
  for stage in json.loads((run/'capture'/group/'stages.json').read_text()):
   grade=grades[stage['id']]
   if grade['final_rank']==1:continue
   trace=stage['numeric_trace'];assert stage['normal_identities_reproduced'] and 'error' not in stage
   if names is None:names=trace['feature_names'];model=trace['model_fingerprint']
   assert names==trace['feature_names'] and model==trace['model_fingerprint']
   goldkeys={key(r) for r in inventory if repoqa_correct_piece({'path':r['path'],'piece_kind':'symbol','entity':r['entity'],'entity_span':r['entity_span']},grade['reference'])};owners={key(r):r for r in trace['owners']};gold=next((owners[k] for k in goldkeys if k in owners),None);chosen=owners[key(grade['top1'])]
   rows.append({'id':stage['id'],'language':language,'reference':grade['reference'],'category':grade['category'],'final_rank':grade['final_rank'],'owner_population':len(inventory),'proposal_population':len(trace['owners']),'gold':gold,'chosen':chosen})
value={'schema':1,'feature_names':names,'feature_count':len(names),'model_fingerprint':model,'cases':len(rows),'pairs':sum(r['gold'] is not None for r in rows),'rows':rows,'source_capture_closure_pins':closure_pins,'producer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'reserve':'CLOSED','status':'Public exposed development observations; no fitting or new acceptance score.','replay':'Load the matching bundled NumericRanker, verify its fingerprint and feature_names, then explain_pair(gold.feature_values, chosen.feature_values). Pair margins reproduce; full population order requires the original full trace retained in the experiment output. C++observations precede the bitwise correction and full-contract variant.'}
path=base/'output/analysis/repoqa-diagnosis-v236/failure-pair-features-v286.json';path.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k not in ('feature_names','rows','source_capture_closure_pins')},indent=2))
