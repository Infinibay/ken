import hashlib,itertools,json,sys
from pathlib import Path
import numpy as np
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');B=R/'output/analysis/choice-trees-ranking-v89';F=R/'output/analysis/context-views-features-source7-v69';D=R/'output/analysis/source7-ranking-v66c/training-matrix.npz';O=R/'output/analysis/choice-learning-gap-v91';O.mkdir(exist_ok=False)
def sha(p):
 with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
array_sha=lambda a:hashlib.sha256(memoryview(np.ascontiguousarray(a)).cast('B')).hexdigest()
r=json.loads((B/'registration.json').read_text());assert r['complete']and r['results']['choice_trees']['strict']['hits']==265
assert all(sha(p)==h for p,h in r['inputs'].items())
with np.load(D)as a:old={k:a[k]for k in('qid','repo','y')}
prior={qid:np.flatnonzero(old['qid']==qid)for qid in set(old['qid'])};qids=[];repos=[];labels=[]
for repo in sorted(r['normalizers']):
 with np.load(F/(repo+'.npz'))as a:values=a['qid']
 for qid,items in itertools.groupby(range(len(values)),key=lambda i:str(values[i])):
  group=list(items);before=prior[qid];assert len(group)==len(before)and all(old['repo'][before]==repo)
  qids.extend([qid]*len(group));repos.extend([repo]*len(group));labels.extend(old['y'][before])
qids,repos,labels=map(np.asarray,(qids,repos,labels));assert array_sha(labels)==r['labels_sha256']
held_scores=np.load(B/'scores.npy');eligible={q for q,v in r['training_groups'].items()if v['skip_reason']is None};assert len(eligible)==358
bindings={str(p):sha(p)for p in(B/'registration.json',B/'scores.npy',D,Path(__file__),R/'experiments/search-engine/cpu-choice-learning-gap-v91.md')};rows=[]
def summarize(mode,held,indices,scores):
 assert len(indices)==len(scores)
 local_qids=qids[indices]
 for qid,items in itertools.groupby(range(len(indices)),key=lambda i:str(local_qids[i])):
  positions=np.array(list(items));source_rows=indices[positions];values=scores[positions];truth=labels[source_rows];assert truth.sum()==1
  best=int(np.argmax(values));positive=float(values[truth==1][0]);negative=float(np.max(values[truth==0]));shifted=values-values.max();p=float(np.exp(shifted[truth==1][0])/np.exp(shifted).sum())
  rows.append({'mode':mode,'held_out':held,'id':qid,'repo':str(repos[source_rows[0]]),'rows':len(values),'hit':bool(truth[best]),'positive_probability':p,'positive_margin':positive-negative})
for held,norm in sorted(r['normalizers'].items()):
 path=B/(held+'-final-training.npz');fold=next(v for v in r['folds']if v['held_out']==held);assert sha(path)==fold['final_training_sha256'];bindings[str(path)]=sha(path)
 for name,digest in ((held+'-native.json',fold['native_model_sha256']),(held+'-numeric.json',fold['model_sha256'])):
  p=B/name;assert sha(p)==digest;bindings[str(p)]=sha(p)
 with np.load(path)as a:indices,scores=a['rows'],a['scores']
 assert all(repos[indices]!=held)and list(dict.fromkeys(qids[indices]))==norm['query_ids']
 summarize('training',held,indices,scores)
 ids=np.flatnonzero((repos==held)&np.isin(qids,list(eligible)));summarize('held',held,ids,held_scores[ids])
summary={}
for mode,expected in(('training',5370),('held',358)):
 selected=[v for v in rows if v['mode']==mode];assert len(selected)==expected
 summary[mode]={'query_occurrences':len(selected),'unique_queries':len({v['id']for v in selected}),'raw_owner_top1_hits':sum(v['hit']for v in selected),'raw_owner_top1_rate':sum(v['hit']for v in selected)/len(selected),'positive_probability_percentiles':dict(zip(('min','p25','p50','p75','max'),map(float,np.percentile([v['positive_probability']for v in selected],[0,25,50,75,100])))),'margin_percentiles':dict(zip(('min','p25','p50','p75','max'),map(float,np.percentile([v['positive_margin']for v in selected],[0,25,50,75,100]))))}
assert all(sha(p)==h for p,h in bindings.items())
(O/'rows.jsonl').write_text(''.join(json.dumps(v)+'\n'for v in rows));report={'scope':'Conditional raw-score diagnostic only; training5370 are correlated15fold repeats of358queries. Full strict89 acceptance remains265/400; no visible evidence/API claim.','bindings':bindings,'summary':summary,'rows_sha256':sha(O/'rows.jsonl'),'complete':True};(O/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(summary,indent=2))
