"""Grade closed union experiment and its shared-logit native control, fixed criterion."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from grade_public_v224 import load_closed_results
from public_benchmarks_v222 import repoqa_correct_piece
base=Path.cwd();out=base/'output/development/repoqa-rust-candidate-pool-v299';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();registration=json.loads((out/'registration.json').read_text());requests=[json.loads(x) for x in (out/'repoqa-requests.jsonl').read_text().splitlines()];assert sha(out/'repoqa-requests.jsonl')==registration['requests_sha256'];responses=load_closed_results(out/'capture',[r['id'] for r in requests]);assert len(responses)==100
union_report=json.loads((out/'report.json').read_text());union_rows={r['id']:r for r in union_report['rows']};refs=json.loads((base/'output/development/repoqa-core-v222/repoqa-references.json').read_text());rows=[];sizes=[];parity=[];errors=[]
for r in requests:
 response=responses[r['id']];record={'id':r['id']};experiment=response.get('experiment')
 if not experiment:
  errors.append({'id':r['id'],'error':response.get('error','missing experiment')});record.update(control_rank=None,union_rank=None,error=errors[-1]['error'])
 else:
  assert experiment['candidate_count']<=20 and experiment['neural_pairs']<=20;parity.append(experiment['native_logit_max_abs_delta']);sizes.append(experiment['candidate_count'])
  control=experiment['native_single_view_control']['results'];assert len(control)<=10
  # Every control result is an authenticated card from the same source catalog.
  for item in control:
   source=Path(r['root'])/item['path'];assert sha(source)==item['source_hash'] and not item.get('stale');lines=source.read_text().splitlines()
   for e in item['evidence']:assert e['content']=='\n'.join(lines[e['start_line']-1:e['end_line']])
  rank=lambda values:next((i for i,item in enumerate(values,1) if repoqa_correct_piece(item,refs[r['id']])),None)
  record.update(control_rank=rank(control),union_rank=rank(response['results']))
 assert int(record['union_rank']==1)==union_rows[r['id']]['top1_piece'] and int(record['union_rank'] is not None)==union_rows[r['id']]['top10_piece'];rows.append(record)
summary={arm:{'queries':100,'top1':sum(r[arm+'_rank']==1 for r in rows),'top10':sum(r[arm+'_rank'] is not None for r in rows)} for arm in ('control','union')}
value={'summary':summary,'errors':errors,'native_control_matches_closed_code_only':summary['control']['top1']==64 and summary['control']['top10']==90,'native_logit_max_abs_delta':max(parity,default=None),'candidate_count':{'min':min(sizes,default=None),'max':max(sizes,default=None),'mean':sum(sizes)/len(sizes) if sizes else None},'new_top1':[r['id'] for r in rows if r['union_rank']==1 and r['control_rank']!=1],'lost_top1':[r['id'] for r in rows if r['union_rank']!=1 and r['control_rank']==1],'new_top10':[r['id'] for r in rows if r['union_rank'] is not None and r['control_rank'] is None],'lost_top10':[r['id'] for r in rows if r['union_rank'] is None and r['control_rank'] is not None],'cost':union_report['cost'],'rows':rows,'registration_sha256':sha(out/'registration.json'),'closure_sha256':sha(out/'capture/closure.json'),'union_grader_report_sha256':sha(out/'report.json'),'grader_sha256':sha(Path(__file__)),'reserve':'CLOSED','production_changed':False,'interpretation':'Original100Rustpublicquestions and unchanged strict callable criterion. Timed experimental source path, sameCPUmodels, <=20neuralpairs, same-source native10single-view control uses shared logits. Includes control presentation/parity check overhead; not normalMCPtransport or blind acceptance. Do not accept if control fails parity or regressions remain unresolved.'};(out/'controlled-report.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='rows'},indent=2))
