"""Use previously exposed references only after all95prior-Java responses close."""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from grade_public_v224 import load_closed_results
from verifiable_grading import identity_hit
base=Path.cwd();out=base/'output/development/prior-java-regression-v276';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();reg=json.loads((out/'registration.json').read_text());assert sha(out/'repoqa-requests.jsonl')==reg['requests_sha256'];requests=[json.loads(x) for x in (out/'repoqa-requests.jsonl').read_text().splitlines()];assert len(requests)==95;responses=load_closed_results(out/'capture',[r['id'] for r in requests]);assert len(responses)==95
for path,digest in reg['public_case_pins'].items():assert sha(Path(path))==digest
for path,digest in reg['old_capture_registration_pins'].items():assert sha(Path(path))==digest
old={r['id']:r for r in map(json.loads,(base/'output/development/public-bounded-symbol-ranking-grade-v214/outcomes.jsonl').read_text().splitlines())};sources=json.loads((out/'repoqa-sources.json').read_text())
# Only consumed/exposed original200+symbol-development200 labels from the old scoring manifest.
grading_registration=json.loads((out/'grading-registration-v278.json').read_text());manifest_path=Path(grading_registration['exposed_manifest']);assert sha(manifest_path)==grading_registration['exposed_manifest_sha256'];assert sha(base/'output/development/public-bounded-symbol-ranking-grade-v214/outcomes.jsonl')==grading_registration['old_outcomes_sha256'];assert sha(Path('/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine/verifiable_grading.py'))==grading_registration['identity_helper_sha256'];manifest=json.loads(manifest_path.read_text());assert {name:digest for cohort in manifest['cohorts'] for name,digest in cohort['exposed_gold_pins'].items()}==grading_registration['reference_pins'];gold={};reference_pins={} 
for cohort in manifest['cohorts']:
 for name,digest in cohort['exposed_gold_pins'].items():
  path=Path(name);assert sha(path)==digest;reference_pins[name]=digest;gold.update({r['id']:r for r in map(json.loads,path.read_text().splitlines())})
assert len(gold)==400 and set(old)==set(gold)
rows=[];results=0;excerpts=0
for request in requests:
 response=responses[request['id']];units=[]
 for item in response.get('results',[]):
  assert item['source_hash']==sources[request['repo_id']]['source_pins'][item['path']] and not item.get('stale');path=Path(request['root'])/item['path'];assert sha(path)==item['source_hash'];lines=path.read_text().splitlines()
  for e in item.get('evidence',[]):assert e['content']=='\n'.join(lines[e['start_line']-1:e['end_line']]);excerpts+=1
  kind=item['piece_kind'];unit={'target_kind':kind,'path':item['path'],'entity':item['entity'] if kind in ('class','symbol') else None,'module_name':item.get('module_name') if kind=='module' else None};units.append(unit);results+=1
 hit=lambda u:identity_hit({'unit':u},gold[request['id']]['acceptable_units']);rank=next((i for i,u in enumerate(units,1) if hit(u)),None);previous=old[request['id']]
 rows.append({k:request[k] for k in ('id','repo_id','cohort','language','piece_kind')}|{'rank':rank,'top1':int(rank==1),'top10':int(rank is not None),'baseline_top1':int(previous['top1']),'baseline_top10':int(previous['recall10']),'error':response.get('error')})
summary={}
for cohort in ('original200','new_symbol200'):
 summary[cohort]={}
 for language in ('all','en'):
  selected=[r for r in rows if r['cohort']==cohort and (language=='all' or r['language']==language)];summary[cohort][language]={'queries':len(selected),**{key:sum(r[key] for r in selected) for key in ('top1','top10','baseline_top1','baseline_top10')}}
v={'queries':95,'summary':summary,'gains_top1':[r['id'] for r in rows if r['top1'] and not r['baseline_top1']],'lost_top1':[r['id'] for r in rows if not r['top1'] and r['baseline_top1']],'gains_top10':[r['id'] for r in rows if r['top10'] and not r['baseline_top10']],'lost_top10':[r['id'] for r in rows if not r['top10'] and r['baseline_top10']],'errors':sum(bool(r['error']) for r in rows),'integrity':{'results':results,'excerpts':excerpts},'reference_pins':reference_pins,'grader_sha256':sha(Path(__file__)),'closure_sha256':sha(out/'capture/closure.json'),'rows':rows,'reserve':'CLOSED','interpretation':'Localized regression on all95prior public Java-repository queries directly affected by constructor eligibility, against unchanged consumed/exposed references. Other305are not recaptured in this run; their inputs/eligibility audit is separate. Normalfind_best API, notMCPtransport. No fresh reserve or release.'};(out/'report.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:x for k,x in v.items() if k not in ('rows','reference_pins')},indent=2))
