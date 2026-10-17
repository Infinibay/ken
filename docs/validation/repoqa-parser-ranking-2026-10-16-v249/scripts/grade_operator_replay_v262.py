from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from public_benchmarks_v222 import repoqa_correct_piece
base=Path.cwd();out=base/'output/analysis/repoqa-bitwise-replay-v261';run=base/'output/development/repoqa-cpp-coverage-v246'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
closure=json.loads((out/'closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['pins'].items():assert sha(out/name)==digest
requests={r['id']:r for r in map(json.loads,(run/'repoqa-requests.jsonl').read_text().splitlines())};sources=json.loads((run/'repoqa-sources.json').read_text());refs=json.loads((base/'output/development/repoqa-core-v222/repoqa-references.json').read_text());old=json.loads((run/'report.json').read_text());old_rows={r['id']:r for r in old['rows']};responses=json.loads((out/'responses.json').read_text());assert len(responses)==100 and {r['id'] for r in responses}==requests.keys()
rows=[];excerpts=0;results=0
for response in responses:
 rid=response['id'];request=requests[rid];ref=refs[rid]
 for item in response['results']:
  path=Path(request['root'])/item['path'];assert sha(path)==item['source_hash']==sources[request['repo_id']]['source_pins'][item['path']] and not item.get('stale');lines=path.read_text().splitlines()
  for e in item['evidence']:assert e['content']=='\n'.join(lines[e['start_line']-1:e['end_line']]);excerpts+=1
  results+=1
 rank=next((i for i,r in enumerate(response['results'],1) if repoqa_correct_piece(r,ref)),None)
 rows.append({'id':rid,'rank':rank,'top1':int(rank==1),'top10':int(rank is not None),'previous_top1':old_rows[rid]['top1_piece'],'previous_top10':old_rows[rid]['top10_piece']})
v={'queries':100,'top1':sum(r['top1'] for r in rows),'top10':sum(r['top10'] for r in rows),'previous_top1':old['summary']['top1_piece'],'previous_top10':old['summary']['top10_piece'],'new_top1':[r['id'] for r in rows if r['top1'] and not r['previous_top1']],'lost_top1':[r['id'] for r in rows if not r['top1'] and r['previous_top1']],'top10_membership_preserved':all(r['top10']==r['previous_top10'] for r in rows),'integrity':{'results':results,'excerpts':excerpts},'closure_sha256':sha(out/'closure.json'),'reference_sha256':sha(base/'output/development/repoqa-core-v222/repoqa-references.json'),'criterion_sha256':sha(Path('/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine/public_benchmarks_v222.py')),'grader_sha256':sha(Path(__file__)),'normal_api_capture':False,'interpretation':'Isolated deterministic policy replay from closed normal calls: same native10, model logits and source. No new encoder/reranker inference or latency/RAM measurement. Not a combined full-contract engine run or blind acceptance.','reserve':'CLOSED','rows':rows}
(out/'report.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps({k:x for k,x in v.items() if k!='rows'},indent=2))
