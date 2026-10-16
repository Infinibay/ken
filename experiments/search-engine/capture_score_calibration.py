"""Pure observer of frozen public search; no labels or candidate/order changes."""
import argparse,hashlib,json,os,resource,subprocess,sys,time
from pathlib import Path
import numpy as np
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.public import find_best
from ken.retrieval.connections import project_connection
from ken.retrieval.piece_ranking import PieceReranker,piece_features,PIECE_FEATURES
from ken.retrieval.piece_search import _unit
from ken.retrieval.piece_cards import canonical
from ken.retrieval.neural_reranker import ONNXReranker

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def main():
 p=argparse.ArgumentParser();p.add_argument('--lock',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--repo');a=p.parse_args();lock=json.loads(a.lock.read_text());engine=Path(lock['engine_root'])
 assert verify_frozen_source(engine)==lock['source_receipt'];assert sha(lock['public_cases'])==lock['public_cases_sha256'];assert sha(__file__)==lock['producer_sha256']
 cases=rows(lock['public_cases']);assert len(cases)==200 and len({r['id'] for r in cases})==200 and not any('acceptable_units' in r for r in cases)
 a.output.mkdir(parents=True,exist_ok=False)
 if not a.repo:
  rec={'lock_sha256':sha(a.lock),'status':'public-only feature capture registered','closed':{}}
  (a.output/'registration.json').write_text(json.dumps(rec,indent=2))
  for repo in sorted({r['repo_id'] for r in cases}):
   with (a.output/(repo+'.log')).open('w') as log:subprocess.run([sys.executable,__file__,'--lock',str(a.lock),'--output',str(a.output/repo),'--repo',repo],check=True,env=os.environ,stdout=log,stderr=subprocess.STDOUT)
   rec['closed'][repo]={n:sha(a.output/repo/n) for n in ['features.npz','observations.jsonl','summary.json']}
   print(json.dumps({'repo':repo,'closed':True}),flush=True)
  rec['status']='ALL200 public observations closed without Gold';(a.output/'registration.json').write_text(json.dumps(rec,indent=2));return
 record={};orig_rank=PieceReranker.rank;orig_score=ONNXReranker.score
 def rank(self,request,pieces,*,expanded_query=None):
  result=orig_rank(self,request,pieces,expanded_query=expanded_query)
  f=piece_features(request,pieces,encoder=self.encoder,stem_words=self.stem_words,expanded_query=expanded_query)
  units=[_unit(q.kind,q.path,q.entity) for q in pieces];idx={canonical(u):i for i,u in enumerate(units)}
  record.update(features=f.values,units=units,piece_order=[idx[canonical(_unit(m.piece.kind,m.piece.path,m.piece.entity))] for m in result],piece_scores=[m.score for m in result],exact=[float(any(m.signals.get('exact',0) for m in q.matches)) for q in pieces])
  return result
 def score(self,query,documents):
  result=orig_score(self,query,documents);record['neural_scores']=result[0];return result
 PieceReranker.rank=rank;ONNXReranker.score=score
 cases=[r for r in cases if r['repo_id']==a.repo];out=[];matrices=[];qids=[]
 expected={r['id']:r for r in rows(Path(lock['expected_capture'])/a.repo/'answers.jsonl')} if lock.get('expected_capture') else None
 with project_connection(Path(lock['roots'][a.repo])) as conn:
  find_best(conn,Path(lock['roots'][a.repo]),'find code that prepares a value',piece_kind='symbol')
  for case in cases:
   record.clear();start=time.perf_counter();response=find_best(conn,Path(lock['roots'][a.repo]),case['query'],scope='files' if case['target_kind'] in {'file','module'} else 'symbols',piece_kind=case['target_kind']);ms=(time.perf_counter()-start)*1000
   assert response.get('ok',True) and not any(r.get('stale') for r in response['results'])
   actual=[{'target_kind':r['piece_kind'],'path':r['path'],'entity':r['entity'] if r['piece_kind'] in {'class','symbol'} else None,'module_name':r.get('module_name') if r['piece_kind']=='module' else None} for r in response['results']]
   if expected is not None:assert actual==expected[case['id']]['units'],f'public order changed: {case["id"]}'
   if 'features' in record:
    x=record.pop('features');assert x.shape==(len(record['units']),len(PIECE_FEATURES)) and np.isfinite(x).all();matrices.append(x);qids.extend([case['id']]*len(x))
    assert len(record['piece_order'])==len(record['neural_scores'])==len(x)
   else:record['exact_bypass']=True
   out.append({'id':case['id'],'repo_id':a.repo,'query':case['query'],'target_kind':case['target_kind'],'baseline_units':actual,'observation_ms':ms,**record})
   print(json.dumps({'id':case['id'],'observed':True}),flush=True)
 np.savez(a.output/'features.npz',x=np.concatenate(matrices) if matrices else np.empty((0,len(PIECE_FEATURES))),qid=np.asarray(qids),features=np.asarray(PIECE_FEATURES))
 (a.output/'observations.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in out));(a.output/'summary.json').write_text(json.dumps({'repo':a.repo,'queries':len(out),'source_receipt':verify_frozen_source(engine),'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','note':'instrumented extra feature extraction; NOT production latency measurement'},indent=2));assert verify_frozen_source(engine)==lock['source_receipt']
if __name__=='__main__':main()
