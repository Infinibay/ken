"""Explain frozen native tree paths for fully closed public misses; no fitting."""
import argparse,gzip,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run=a.run.resolve();registration=json.loads((run/'registration.json').read_text());engine=Path(registration['engine']);sys.path.insert(0,str(engine/'src'))
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.model import EntityKey
import numpy as np
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
closure=json.loads((run/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['response_pins'].items():assert sha(run/'capture'/name)==digest
registry=json.loads((engine/'src/ken/retrieval/data/production-rank-models.json').read_text());model=NumericRanker.from_dict(json.loads(gzip.decompress((engine/'src/ken/retrieval/data'/registry['native']['file']).read_bytes())));assert model.fingerprint==registry['native']['fingerprint']
ledger=json.loads(a.ledger.read_text());rows=[]
for group in sorted({r['repo_id'] for r in ledger['rows']}):
 stages={r['id']:r for r in json.loads((run/'capture'/group/'stages.json').read_text())}
 for row in ledger['rows']:
  if row['repo_id']!=group or row['final_rank']==1 or not row['matching_context_owners']:continue
  stage=stages[row['id']];trace=RankingTrace.from_dict(stage['numeric_trace'],model)
  ref=row['reference'];wanted=[o for o in stage['numeric_trace']['owners'] if o['path']==ref['path'] and (o['entity'].get('qualname') or '').replace('::','.').rsplit('.',1)[-1]==ref['name']]
  # Reference leaf can have overloads: use inventory's exact source extent.
  inventory=json.loads((run/'capture'/group/'context-owners.json').read_text());accepted=[i for i in inventory if i['path']==ref['path'] and i['entity_span']['end_line']==ref['end_line'] and ref['start_line']+1-10<=i['entity_span']['start_line']<=ref['start_line']+1 and (i['entity'].get('qualname') or '').replace('::','.').rsplit('.',1)[-1]==ref['name']]
  keys=[EntityKey(path=i['path'],**i['entity']) for i in accepted];true=next(o for o in wanted if EntityKey(path=o['path'],**o['entity']) in keys);gold=EntityKey(path=true['path'],**true['entity'])
  chosen=EntityKey(path=row['top1']['path'],**row['top1']['entity']);pair=trace.compare(gold,chosen)
  numeric=pair['numeric'];groups=sorted(numeric['branch_margin_by_feature'].items(),key=lambda kv:abs(kv[1]),reverse=True)
  rows.append({'id':row['id'],'reference':ref,'gold_native_owner_rank':true['rank'],'chosen_final':row['top1']['entity'],'gold_score':numeric['left_score'],'chosen_score':numeric['right_score'],'gold_minus_chosen_margin':numeric['margin'],'top_interaction_groups':[{'feature':name,'margin':value,'gold':pair['left']['feature_values'][model.features.index(name)],'chosen':pair['right']['feature_values'][model.features.index(name)]} for name,value in groups[:15]],'all_groups':numeric['branch_margin_by_feature'],'attribution':numeric['attribution'],'rounding_residual':numeric['rounding_residual']})
value={'rows':rows,'cases':len(rows),'model_fingerprint':model.fingerprint,'closure_sha256':sha(run/'capture/closure.json'),'ledger_sha256':sha(a.ledger),'producer_sha256':sha(Path(__file__)),'no_fit':True,'reserve':'CLOSED'};a.out.write_text(json.dumps(value,indent=2)+'\n');print(json.dumps({'cases':len(rows),'out':str(a.out),'model':model.fingerprint}))
