"""Apply the unchanged public function-identity criterion to a closed variant."""
import argparse, collections, json, math, sys
from pathlib import Path
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from grade_public_v224 import load_closed_results, percentile
from public_benchmarks_v222 import repoqa_correct_piece, sha
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args();out=args.out.resolve();base=Path.cwd();old=base/'output/development/repoqa-core-v222'
registration=json.loads((out/'registration.json').read_text());assert sha(out/'repoqa-requests.jsonl')==registration['requests_sha256'];assert sha(out/'repoqa-sources.json')==registration['sources_sha256']
requests=[json.loads(x) for x in (out/'repoqa-requests.jsonl').read_text().splitlines()];ids=[r['id'] for r in requests]
responses=load_closed_results(out/'capture',ids)
original_requests={r['id']:r for r in map(json.loads,(old/'repoqa-requests.jsonl').read_text().splitlines())}
for row in requests:assert {k:v for k,v in row.items() if k!='root'}=={k:v for k,v in original_requests[row['id']].items() if k!='root'}
assert sha(old/'repoqa-report-v224.json')==registration['baseline_report_sha256']
old_report=json.loads((old/'repoqa-report-v224.json').read_text());old_rows={r['id']:r for r in old_report['rows']}
refs=json.loads((old/'repoqa-references.json').read_text());sources=json.loads((out/'repoqa-sources.json').read_text())
original_responses=load_closed_results(old/'repoqa-capture-v224',list(original_requests))
indexed={};provenance=[]
for group in sources:
 folder=out/'capture'/group
 if (folder/'indexed-owners.json').is_file():indexed[group]=json.loads((folder/'indexed-owners.json').read_text())
 if (folder/'provenance.json').is_file():provenance.append(json.loads((folder/'provenance.json').read_text()))
rows=[];verified_results=0;verified_excerpts=0;source_cache={}
for request in requests:
 rid=request['id'];ref=refs[rid];response=responses[rid];results=response.get('results',[]);assert len(results)<=10
 for item in results:
  assert not item.get('stale');assert item['source_hash']==sources[request['repo_id']]['source_pins'][item['path']]
  path=Path(request['root'])/item['path']
  if str(path) not in source_cache:
   assert sha(path)==item['source_hash'];source_cache[str(path)]=path.read_text().splitlines()
  lines=source_cache[str(path)];span=item['entity_span'];assert 1<=span['start_line']<=span['end_line']<=max(1,len(lines))
  for evidence in item.get('evidence',[]):
   assert evidence['content']=='\n'.join(lines[evidence['start_line']-1:evidence['end_line']]);verified_excerpts+=1
  verified_results+=1
 ranks=[i for i,item in enumerate(results,1) if repoqa_correct_piece(item,ref)]
 rank=ranks[0] if ranks else None
 owners=[s for s in indexed.get(request['repo_id'],[]) if s['path']==ref['path'] and repoqa_correct_piece({'path':s['path'],'piece_kind':'symbol','entity':{'kind':s['kind'],'qualname':s['qualname']},'entity_span':{'start_line':s['start_line'],'end_line':s['end_line']}},ref)]
 rows.append({'id':rid,'repo_id':request['repo_id'],'language':ref['language'],'reference':ref,'correct_ranks':ranks,'top1_piece':int(rank==1),'top10_piece':int(rank is not None),'ndcg10_piece':1/math.log2(rank+1) if rank else 0,'mrr10_piece':1/rank if rank else 0,'top1_file':int(bool(results and results[0]['path']==ref['path'])),'top10_file':int(any(r['path']==ref['path'] for r in results)),'indexed':bool(owners),'indexed_with_passages':any(s['passages'] for s in owners),'baseline_top1_piece':old_rows[rid]['top1_piece'],'baseline_top10_piece':old_rows[rid]['top10_piece'],'error':response.get('error'),'top1':{k:results[0][k] for k in ('path','entity','entity_span')} if results else None})
metrics=['top1_piece','top10_piece','top1_file','top10_file','ndcg10_piece','mrr10_piece']
def summary(group):return {'queries':len(group),**{k:sum(r[k] for r in group) for k in metrics[:4]},**{k:sum(r[k] for r in group)/len(group) for k in metrics[4:]},'indexed':sum(r['indexed'] for r in group),'indexed_with_passages':sum(r['indexed_with_passages'] for r in group),'errors':sum(bool(r['error']) for r in group),'baseline_top1_piece':sum(r['baseline_top1_piece'] for r in group),'baseline_top10_piece':sum(r['baseline_top10_piece'] for r in group)}
def rss(r,key):return r[key]*(1 if r['rss_unit']=='bytes' else 1024)
def timings(values):return {'p50_ms':percentile(values,.5),'p95_ms':percentile(values,.95),'max_ms':max(values,default=None)}
cost={'queries':timings([r['elapsed_ms'] for r in responses.values() if 'elapsed_ms' in r]),'baseline_queries':timings([original_responses[rid]['elapsed_ms'] for rid in ids if 'elapsed_ms' in original_responses[rid]]),'cpu':timings([r['cpu_ms'] for r in responses.values() if 'cpu_ms' in r]),'query_process_peak_rss_bytes':max((rss(r,'query_process_peak_rss_native') for r in provenance),default=None),'prepare_process_peak_rss_bytes':max((rss(r,'prepare_child_peak_rss_native') for r in provenance),default=None),'providers':sorted({provider for r in provenance for provider in r['providers']}),'note':'Observed CPU timings with other benchmark/development activity; not an isolated latency experiment.'}
report={'engine_manifest_sha256':registration['engine_manifest_sha256'],'closure_sha256':sha(out/'capture/closure.json'),'grader_sha256':sha(Path(__file__)),'reference_sha256':sha(old/'repoqa-references.json'),'criterion_sha256':sha(Path('/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine/public_benchmarks_v222.py')),'summary':summary(rows),'by_repo':{key:summary([r for r in rows if r['repo_id']==key]) for key in sources},'new_top1':[r['id'] for r in rows if r['top1_piece'] and not r['baseline_top1_piece']],'lost_top1':[r['id'] for r in rows if not r['top1_piece'] and r['baseline_top1_piece']],'new_top10':[r['id'] for r in rows if r['top10_piece'] and not r['baseline_top10_piece']],'lost_top10':[r['id'] for r in rows if not r['top10_piece'] and r['baseline_top10_piece']],'cost':cost,'integrity':{'results':verified_results,'excerpts':verified_excerpts},'rows':rows,'interpretation':'Public RepoQA development diagnostic, identical original English queries and 100-case denominator; exact path/function-identity proxy. Not official LLM SNF or private acceptance.','reserve':'CLOSED','release':False}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('rows','by_repo')},indent=2))
