import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from public_benchmarks_v222 import repoqa_correct_piece
base=Path.cwd();out=base/'output/analysis/repoqa-view-consensus-v272';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();closure=json.loads((out/'closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==200
for name,digest in closure['pins'].items():assert sha(out/name)==digest
refpath=base/'output/development/repoqa-core-v222/repoqa-references.json';refs=json.loads(refpath.read_text());pred=json.loads((out/'predictions.json').read_text());rows=[]
for p in pred:
 ranks={variant:next((i for i,item in enumerate(order,1) if repoqa_correct_piece(item,refs[p['id']])),None) for variant,order in p['orders'].items()};assert len({r is not None for r in ranks.values()})==1
 rows.append({'id':p['id'],'language':p['language'],'ranks':ranks})
summary={}
for variant in rows[0]['ranks']:
 summary[variant]={}
 for language in ('cpp','rust','all'):
  subset=[r for r in rows if language=='all' or r['language']==language]
  summary[variant][language]={'queries':len(subset),'top1':sum(r['ranks'][variant]==1 for r in subset),'top10':sum(r['ranks'][variant] is not None for r in subset),'gains_from_mean':[r['id'] for r in subset if r['ranks'][variant]==1 and r['ranks']['equal_mean']!=1],'losses_from_mean':[r['id'] for r in subset if r['ranks'][variant]!=1 and r['ranks']['equal_mean']==1]}
assert summary['equal_mean']['cpp']['top1']==69 and summary['equal_mean']['rust']['top1']==59
value={'summary':summary,'rows':rows,'closure_sha256':sha(out/'closure.json'),'reference_sha256':sha(refpath),'grader_sha256':sha(Path(__file__)),'no_fit':True,'reserve':'CLOSED','production_changed':False,'interpretation':'Exposed public development diagnostic, same native10 and frozen logits. Not a blind evaluation, new encoder run, proposal change or current combined-engine capture. Alternative compositions are not accepted for production without prior-development regression checks.'};(out/'report.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps({name:{lang:{k:v for k,v in s.items() if k in ('queries','top1','top10')} for lang,s in values.items()} for name,values in summary.items()},indent=2))
