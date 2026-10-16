"""Fixed two-arm score calibration on exposed development, never reserve labels."""
import argparse,hashlib,itertools,json,time
from pathlib import Path
import numpy as np
from lightgbm import LGBMRanker
from ken.bench.numeric_export import export_numeric_ranker
from ken.retrieval.intent import requested_piece_path
from ken.retrieval.model import SearchRequest
from ken.retrieval.piece_ranking import PIECE_FEATURES
from calibration_training import training_selection
from score_calibration import CALIBRATION_FEATURES,FULL_FEATURES,calibration_features
from verifiable_grading import identity_hit

PARAMETERS=dict(n_estimators=160,num_leaves=15,min_child_samples=40,reg_lambda=2,
 learning_rate=.08,lambdarank_truncation_level=5,n_jobs=1,random_state=42)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def summarize(outcomes):
 def count(group):return {'queries':len(group),'top1':sum(x['top1'] for x in group),'recall10':sum(x['recall10'] for x in group)}
 return {'total':count(outcomes),**{field:{v:count([x for x in outcomes if x[field]==v]) for v in sorted({x[field] for x in outcomes})} for field in ['cohort','target_kind','repo_id','language','query_kind']}}
def fitted(x,y,qids,repos,kinds,names,held):
 mask,weights=training_selection(qids,repos,kinds,y,held_out=held)
 sizes=[len(list(g)) for _,g in itertools.groupby(qids[mask])]
 assert sum(sizes)==int(mask.sum())
 f=LGBMRanker(objective='lambdarank',verbosity=-1,**PARAMETERS)
 f.fit(x[mask],y[mask],group=sizes,sample_weight=weights,feature_name=list(names))
 model=export_numeric_ranker(f.booster_.dump_model(),features=names)
 assert np.array_equal(model.predict(x),f.booster_.predict(x))
 return model,{'held_out':held,'training_queries':len(set(qids[mask])),'training_repos':sorted(set(repos[mask])),'queries_by_kind':{k:len(set(qids[mask & (kinds==k)])) for k in sorted(set(kinds))},'fingerprint':model.fingerprint}
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();lock=json.loads(a.manifest.read_text())
 assert lock['scope']=='EXPOSED_DEVELOPMENT_ONLY_ORIGINAL200_PLUS_NEW_SYMBOL200'
 review=lock['independent_development_reference_review'];assert review['status']=='APPROVED' and sha(review['path'])==review['sha256']
 assert lock['parameters']==PARAMETERS
 assert {c['name'] for c in lock['cohorts']}=={'original200','new_symbol200'}
 for path,digest in lock['code_pins'].items():assert sha(path)==digest
 a.output.mkdir(parents=True,exist_ok=False)
 registration={'scope':lock['scope'],'input_manifest_sha256':sha(a.manifest),'parameters':PARAMETERS,'candidates':['A_compact34','B_source296'],'status':'registered before opening exposed-development Gold','folds':{}}
 (a.output/'registration.json').write_text(json.dumps(registration,indent=2))
 cases={};obs={};source={};gold={}
 for cohort in lock['cohorts']:
  assert sha(cohort['public_cases'])==cohort['public_sha256'];public=rows(cohort['public_cases']);assert len(public)==200
  regpath=Path(cohort['capture'])/'registration.json';assert sha(regpath)==cohort['capture_registration_sha256'];reg=json.loads(regpath.read_text());assert reg['status']=='ALL200 public observations closed without Gold'
  local={}
  for repo,pins in reg['closed'].items():
   for filename,digest in pins.items():assert sha(Path(cohort['capture'])/repo/filename)==digest
   data=np.load(Path(cohort['capture'])/repo/'features.npz',allow_pickle=False)
   assert data['features'].tolist()==list(PIECE_FEATURES)
   for r in rows(Path(cohort['capture'])/repo/'observations.jsonl'):
    assert r['repo_id']==repo and r['id'] not in obs
    ix=np.flatnonzero(data['qid']==r['id']);assert bool(len(ix))!=bool(r.get('exact_bypass'))
    source[r['id']]=data['x'][ix];obs[r['id']]=r;local[r['id']]=r
  assert set(local)=={c['id'] for c in public}
  for c in public:
   assert c['id'] not in cases and 'acceptable_units' not in c
   assert obs[c['id']]['query']==c['query'] and obs[c['id']]['target_kind']==c['target_kind']
   cases[c['id']]={**c,'cohort':cohort['name'],'query_kind':c.get('query_kind',c.get('query_style','unspecified'))}
  for path,digest in cohort['exposed_gold_pins'].items():
   assert sha(path)==digest
   for g in rows(path):assert g['id'] not in gold;gold[g['id']]=g
 assert set(cases)==set(obs)==set(gold) and len(cases)==400
 # The implementer is authorized to see all these development labels. No old
 # consumed acceptance Gold or new private reserve paths are admitted in lock.
 qids=[];repos=[];kinds=[];labels=[];xlow=[];xfull=[];groups={};start=0
 for qid,r in obs.items():
  if r.get('exact_bypass'):continue
  units=r['units'];n=len(units);assert len(source[qid])==n
  qids.extend([qid]*n);repos.extend([r['repo_id']]*n);kinds.extend([r['target_kind']]*n)
  labels.extend(int(identity_hit({'unit':u},gold[qid]['acceptable_units'])) for u in units)
  kwargs={k:r[k] for k in ['piece_order','piece_scores','neural_scores','exact']}
  xlow.append(calibration_features(source[qid],**kwargs));xfull.append(calibration_features(source[qid],**kwargs,include_source=True));groups[qid]=np.arange(start,start+n);start+=n
 qids,repos,kinds,y=map(np.asarray,(qids,repos,kinds,labels));matrices={'A_compact34':np.concatenate(xlow),'B_source296':np.concatenate(xfull)};schemas={'A_compact34':CALIBRATION_FEATURES,'B_source296':FULL_FEATURES}
 def grade(predictions=None):
  outcomes=[];orders=[]
  for qid,r in obs.items():
   c=cases[qid];units=r['baseline_units']
   if predictions is not None and qid in groups:
    ix=groups[qid];named=requested_piece_path(SearchRequest(c['query']))
    order=sorted(range(len(ix)),key=lambda i:(-int(named is not None and r['units'][i]['path']==named),-r['exact'][i],-predictions[ix[i]],i));units=[r['units'][i] for i in order]
    assert sorted(json.dumps(u,sort_keys=True) for u in units)==sorted(json.dumps(u,sort_keys=True) for u in r['baseline_units'])
   hit=lambda u:identity_hit({'unit':u},gold[qid]['acceptable_units'])
   outcomes.append({k:c.get(k,'unspecified') for k in ['cohort','repo_id','target_kind','language','query_kind']}|{'id':qid,'top1':bool(units and hit(units[0])),'recall10':any(hit(u) for u in units)})
   orders.append({'id':qid,'units':units})
  return outcomes,orders
 baseline,_=grade();results={'baseline':summarize(baseline)}
 for variant,x in matrices.items():
  scores=np.empty(len(x));folds=[]
  for held in sorted(set(repos)):
   model,receipt=fitted(x,y,qids,repos,kinds,schemas[variant],held);assert held not in receipt['training_repos'];folds.append(receipt)
   test=repos==held;scores[test]=model.predict(x[test]);(a.output/(variant+'-'+held+'.json')).write_text(json.dumps(model.to_dict(),separators=(',',':')))
  assert np.isfinite(scores).all();outcomes,orders=grade(scores);results[variant]=summarize(outcomes)
  (a.output/(variant+'-cv-outcomes.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in outcomes));(a.output/(variant+'-cv-orders.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in orders));registration['folds'][variant]=folds
  print(json.dumps({'variant':variant,'results':results[variant]}),flush=True)
 selected=max(matrices,key=lambda v:results[v]['total']['top1'])
 model,receipt=fitted(matrices[selected],y,qids,repos,kinds,schemas[selected],None)
 (a.output/'selected-pooled-model.json').write_text(json.dumps(model.to_dict(),separators=(',',':')))
 outcomes,orders=grade(model.predict(matrices[selected]));results['selected_pooled_DEVELOPMENT_TRAINING_REUSE']=summarize(outcomes)
 (a.output/'selected-pooled-development-orders.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in orders))
 (a.output/'selected-pooled-development-outcomes.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in outcomes))
 registration.update(status='ALL development CV and pooled fit closed; private acceptance NOT executed',selected=selected,pooled_receipt=receipt,model_file_sha256=sha(a.output/'selected-pooled-model.json'))
 (a.output/'registration.json').write_text(json.dumps(registration,indent=2));(a.output/'summary.json').write_text(json.dumps(results,indent=2));print(json.dumps({'selected':selected,'model_fingerprint':model.fingerprint}),flush=True)
if __name__=='__main__':main()
