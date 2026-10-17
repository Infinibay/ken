"""Analyze fully closed source-only observations against unchanged public references."""
import argparse,collections,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'/Users/andres/.codex/worktrees/compact-default-output/ken/experiments/search-engine')
from public_benchmarks_v222 import repoqa_correct_piece
p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run=a.run.resolve();capture=run/'capture'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
closure=json.loads((capture/'closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['response_pins'].items():assert sha(capture/name)==digest,name
requests=[json.loads(x) for x in (run/'repoqa-requests.jsonl').read_text().splitlines()];report=json.loads(a.report.read_text());grades={r['id']:r for r in report['rows']};assert len(requests)==len(grades)==100
registration=json.loads((run/'registration.json').read_text());assert sha(run/'repoqa-requests.jsonl')==registration['requests_sha256']
def key(value):return json.dumps([value['path'],value.get('entity') or {}],sort_keys=True,separators=(',',':'))
def rank(values,correct):return next((i for i,v in enumerate(values,1) if key(v) in correct),None)
def candidate(value):return {'path':value['path'],'piece_kind':'symbol','entity':value['entity'],'entity_span':value['entity_span']}
rows=[];all_ids=[]
for group in sorted({r['repo_id'] for r in requests}):
 folder=capture/group;inventory=json.loads((folder/'context-owners.json').read_text());stages=json.loads((folder/'stages.json').read_text());all_ids.extend(s['id'] for s in stages)
 for s in stages:
  assert 'error' not in s,(s['id'],s.get('error'));assert s['normal_identities_reproduced']
  grade=grades[s['id']];ref=grade['reference'];correct={key(v) for v in inventory if repoqa_correct_piece(candidate(v),ref)}
  original,expanded=s['contextual_original'],s['contextual_expanded'];assert len(original)==len(expanded)==len(inventory)
  scores=[max(x,y) for x,y in zip(original,expanded,strict=True)];order=sorted(range(len(scores)),key=lambda i:-scores[i]);symbol_order=[i for i in order if inventory[i]['entity']['kind'] in {'function','method','constructor','destructor','const','constant'}]
  contextual_rank=rank([inventory[i] for i in order],correct);contextual_symbol_rank=rank([inventory[i] for i in symbol_order],correct)
  native=[{'path':c['unit']['path'],'entity':c['unit']['entity']} for c in s['native_cards']]
  results=s['diagnostic_response']['results'];final_rank=rank(results,correct);assert int(final_rank==1)==grade['top1_piece'] and int(final_rank is not None)==grade['top10_piece']
  by_piece=sorted(results,key=lambda r:r['signals']['piece_rank'])
  score_rank=lambda score:rank(sorted(by_piece,key=lambda r:-score(r)),correct)
  native_rank=rank(native,correct);numeric_rank=rank(s['numeric_order'],correct);proposal=next((v for v in s['proposals'] if key(v) in correct),None)
  if not correct:category='missing_index_or_canonical_identity'
  elif proposal is None:category='missing_proposal'
  elif native_rank is None:category='numeric_selection_outside_native10'
  elif final_rank!=1:category='inside_native10_not_first'
  else:category='correct_first'
  top=s['diagnostic_response']['results'][0] if results else None
  row={'id':s['id'],'repo_id':group,'reference':ref,'indexed_reference':grade['indexed'],'matching_context_owners':len(correct),'category':category,'final_rank':final_rank,'native_rank':native_rank,'numeric_owner_rank':numeric_rank,'contextual_all_rank':contextual_rank,'contextual_symbol_rank':contextual_symbol_rank,'static_family_rank':round(1/proposal['signals']['proposal_static']) if proposal and proposal['signals'].get('proposal_static') else None,'contextual_family_rank':round(1/proposal['signals']['proposal_code']) if proposal and proposal['signals'].get('proposal_code') else None,'card_neural_rank':score_rank(lambda r:r['signals']['neural_score']),'code_neural_rank':score_rank(lambda r:r['signals']['symbol_ranking']['code_score']),'mean_neural_rank':score_rank(lambda r:r['signals']['symbol_ranking']['mean_score']),'piece_model_rank':rank(by_piece,correct),'top1':{k:top[k] for k in ('path','entity','entity_span','signals')} if top else None,'gold_results':[{'rank':i,**r} for i,r in enumerate(results,1) if key(r) in correct]}
  rows.append(row)
assert sorted(all_ids)==sorted(r['id'] for r in requests) and len(rows)==100
metrics={name:{'top1':sum(r[name]==1 for r in rows),'top10':sum(r[name] is not None and r[name]<=10 for r in rows),'present':sum(r[name] is not None for r in rows)} for name in ('final_rank','native_rank','numeric_owner_rank','contextual_all_rank','contextual_symbol_rank','static_family_rank','card_neural_rank','code_neural_rank','mean_neural_rank','piece_model_rank')}
value={'closure_sha256':sha(capture/'closure.json'),'report_sha256':sha(a.report),'producer_sha256':sha(Path(__file__)),'queries':100,'categories':dict(collections.Counter(r['category'] for r in rows)),'metrics':metrics,'native_first_lost_by_final':[r['id'] for r in rows if r['native_rank']==1 and r['final_rank']!=1],'final_first_promoted_from_native':[r['id'] for r in rows if r['native_rank']!=1 and r['final_rank']==1],'mean_first_lost_by_preferences':[r['id'] for r in rows if r['mean_neural_rank']==1 and r['final_rank']!=1],'final_first_promoted_by_preferences':[r['id'] for r in rows if r['mean_neural_rank']!=1 and r['final_rank']==1],'rows':rows,'private_reserve':'CLOSED','no_fit':True,'criterion_unchanged':True,'interpretation':'Closed public development diagnostic. Raw contextual ranks include all logged owners; symbol ranks exclude non-symbol kinds. Card/code/mean comparisons are reorderings of the same native10 only and cannot recover absent candidates. Family ranks are proposal observations, not independent end-to-end benchmark runs.'}
a.out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({k:v for k,v in value.items() if k!='rows'},indent=2))
