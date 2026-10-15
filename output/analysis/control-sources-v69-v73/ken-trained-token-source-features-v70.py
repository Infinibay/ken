"""Complete source7 trained96dim token vectors before public-only query features."""
import collections,gc,hashlib,itertools,json,resource,sqlite3,sys,time
from pathlib import Path
import numpy as np
import ken
ROOT=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');ENGINE=Path(ken.__file__).resolve().parents[2];sys.path.insert(0,str(ENGINE/'experiments/search-engine'))
from trained_token_encoder import TrainedTokenEncoder,TOKEN_POLICY
from late_interaction import STATISTICS,compact_tokens,interaction_statistics
from replay import load_pools
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import EntityKey
BASE=ROOT/'output/analysis/c-source-reindex-v66c';VIEWS=ROOT/'output/analysis/context-views-source7-v69';PARENT=ROOT/'output/analysis/context-views-features-source7-v69';OUT=ROOT/'output/analysis/trained-token-features-v70';OUT.mkdir(exist_ok=False)
def sha(p):
 with Path(p).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
source_reg=json.loads((VIEWS/'registration.json').read_text());assert len(source_reg['source_repos'])==16;receipt=verify_frozen_source(ENGINE);assetfile=ROOT/'output/models/answerai-colbert-small-research-v68.json';context=TrainedTokenEncoder(json.loads(assetfile.read_text()));roots={k:Path(v)for k,v in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()};names=('contract','implementation');manifest={'scope':'ALL16 complete source7 canonical contract/body units before query access; official33.4M normalized96 token head/int8 source compaction; prepared complement control only, no replacement/quality/latency claim','script_sha256':sha(__file__),'engine_receipt':receipt,'protocol_sha256':sha(ROOT/'experiments/search-engine/cpu-trained-token-control-v70.md'),'asset_registration_sha256':sha(assetfile),'encoder':context.identity,'token_policy':TOKEN_POLICY,'source_view_registration_sha256':sha(VIEWS/'registration.json'),'source_repos':{},'query_repos':{}};(OUT/'registration.json').write_text(json.dumps(manifest,indent=2))
for repo,root in sorted(roots.items()):
 clock=time.perf_counter();prior=source_reg['source_repos'][repo];input_db=VIEWS/f'{repo}-source.db';assert sha(input_db)==prior['source_db_sha256']
 for path,digest in prior['source_files'].items():assert sha(root/path)==digest
 source=sqlite3.connect(f'file:{input_db}?mode=ro',uri=True);db=sqlite3.connect(OUT/f'{repo}-source.db');db.execute('CREATE TABLE owners(entity TEXT,source_hash TEXT,view TEXT,text_hash TEXT,PRIMARY KEY(entity,view))');db.execute('CREATE TABLE units(text_hash TEXT PRIMARY KEY,start_token INT,token_count INT,token_ids BLOB,original_offsets BLOB)');owners=source.execute('SELECT entity,source_hash,view,text_hash FROM owners ORDER BY entity,view').fetchall();assert len(owners)==prior['units']==2*prior['owners'];db.executemany('INSERT INTO owners VALUES (?,?,?,?)',owners);cursor=0;max_error=0.;input_tokens=0;units=0
 with (OUT/f'{repo}-tokens.i8').open('wb')as stream:
  for key,text in source.execute('SELECT text_hash,text FROM texts ORDER BY vector_index'):
   assert hashlib.sha256(text.encode()).hexdigest()==key;encoded=context.encode(text,is_query=False);packed=compact_tokens(encoded.vectors);ids=np.asarray(encoded.ids,dtype=np.int32);offsets=np.asarray(encoded.offsets,dtype=np.int32);assert len(packed)==len(ids)==len(offsets)>0;dequant=packed.astype(np.float32);dequant/=np.linalg.norm(dequant,axis=1,keepdims=True);max_error=max(max_error,float((1-(encoded.vectors*dequant).sum(axis=1)).max()));db.execute('INSERT INTO units VALUES (?,?,?,?,?)',(key,cursor,len(ids),ids.tobytes(),offsets.tobytes()));stream.write(packed.tobytes());cursor+=len(ids);input_tokens+=context.calls[-1]['input_tokens'];units+=1
   if units%256==0:stream.flush();db.commit();print(json.dumps({'source_progress':repo,'units':units,'total':prior['unique_texts'],'tokens':cursor}),flush=True);context.calls.clear()
 db.commit();assert units==prior['unique_texts'];frequency=collections.Counter()
 for entity,records in itertools.groupby(owners,key=lambda row:row[0]):
  records=list(records);assert {r[2]for r in records}==set(names);tokens=set()
  for _,_,_,key in records:tokens.update(map(int,np.frombuffer(db.execute('SELECT token_ids FROM units WHERE text_hash=?',(key,)).fetchone()[0],dtype=np.int32)))
  frequency.update(tokens)
 counts=np.zeros(30522,dtype=np.uint32)
 for token,count in frequency.items():assert 0<count<=prior['owners'];counts[token]=count
 np.save(OUT/f'{repo}-df.npy',counts);db.close();source.close();assert sha(input_db)==prior['source_db_sha256'];metadata={'owners':prior['owners'],'units':len(owners),'unique_texts':units,'source_files':prior['source_files'],'source_generation':prior['source_generation'],'selected_tokens':cursor,'actual_prefix_tokens':input_tokens,'token_bytes':(OUT/f'{repo}-tokens.i8').stat().st_size,'max_self_cosine_error_after_source_quantization':max_error,'source_view_db_sha256':sha(input_db),'source_db_sha256':sha(OUT/f'{repo}-source.db'),'token_sha256':sha(OUT/f'{repo}-tokens.i8'),'df_sha256':sha(OUT/f'{repo}-df.npy'),'ms':(time.perf_counter()-clock)*1000,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss};assert metadata['token_bytes']==cursor*96;manifest['source_repos'][repo]=metadata;(OUT/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'source_complete':repo,'owners':prior['owners'],'units':units,'tokens':cursor,'bytes':cursor*96}),flush=True);context.calls.clear();del owners,frequency;gc.collect()
assert len(manifest['source_repos'])==16 and verify_frozen_source(ENGINE)==receipt
parent_reg=json.loads((PARENT/'registration.json').read_text());assert len(parent_reg['query_repos'])==16;requests={}
for file in sorted((BASE/'requests').glob('*.jsonl')):
 for row in map(json.loads,file.read_text().splitlines()):assert set(row)=={'id','repo_id','request'};requests[row['id']]=row
assert len(requests)==400;pools=load_pools(BASE,requests);saved={r['id']:r for r in map(json.loads,(BASE/'candidates.jsonl').read_text().splitlines())};features=(*parent_reg['features'],*(f'trained_token_{q}_{view}_{stat}'for q in ('original','expanded')for view in names for stat in (*STATISTICS,'mean_to_max','mean_reciprocal_rank')));assert len(features)==283;manifest['features']=features;manifest['parent_features_registration_sha256']=sha(PARENT/'registration.json');query_cache={};bindings=[]
for repo in sorted(roots):
 parent=np.load(PARENT/f'{repo}.npz');assert sha(PARENT/f'{repo}.npz')==parent_reg['query_repos'][repo]['output_sha256'];qids=parent['qid'];db=sqlite3.connect(f'file:{OUT/(repo+"-source.db")}?mode=ro',uri=True);owners={(EntityKey(**json.loads(e)),view):(digest,key)for e,digest,view,key in db.execute('SELECT * FROM owners')};units={key:(start,count)for key,start,count in db.execute('SELECT text_hash,start_token,token_count FROM units')};db.close();vectors=np.memmap(OUT/f'{repo}-tokens.i8',mode='r',dtype=np.int8,shape=(manifest['source_repos'][repo]['selected_tokens'],96));df=np.load(OUT/f'{repo}-df.npy');extra=[];timings=[]
 for qid,records in itertools.groupby(range(len(qids)),key=lambda i:str(qids[i])):
  clock=time.perf_counter();indexes=list(records);pool=pools[qid];assert len(pool)==len(indexes);bypass=len(pool)==1 and bool(pool[0].signals.get('exact'));columns=[]
  for query_view,query in [('original',requests[qid]['request']['query']),('expanded',saved[qid]['expanded_query'])]:
   binding={'id':qid,'view':query_view,'text_sha256':hashlib.sha256(query.encode()).hexdigest(),'exact_numeric_bypass':bypass}
   if bypass:bindings.append(binding);continue
   if query not in query_cache:query_cache[query]=context.encode(query,is_query=True)
   encoded=query_cache[query];binding.update(token_ids_sha256=hashlib.sha256(encoded.ids.tobytes()).hexdigest(),vectors_sha256=hashlib.sha256(encoded.vectors.tobytes()).hexdigest());bindings.append(binding);weights=np.log1p(manifest['source_repos'][repo]['owners']/(1+df[encoded.ids].astype(np.float64)))
   for view in names:
    summaries=[]
    for candidate in pool:
     digest,key=owners[(candidate.entity,view)];assert digest==candidate.passages[0].source_hash;start,count=units[key];summaries.append(interaction_statistics(encoded.vectors,vectors[start:start+count],weights))
    values=np.asarray(summaries);means=values[:,0];ranks=np.empty(len(means));ranks[np.argsort(-means,kind='stable')]=np.arange(1,len(means)+1);columns.extend([*values.T,means-means.max(),1/ranks])
  extra.extend(np.zeros((1,32))if bypass else np.stack(columns,axis=1));timings.append({'id':qid,'ms':(time.perf_counter()-clock)*1000,'owners':len(pool),'exact_numeric_bypass':bypass})
 matrix=np.column_stack((parent['x'],extra));assert matrix.shape==(len(qids),283)and np.isfinite(matrix).all();np.savez_compressed(OUT/f'{repo}.npz',x=matrix,qid=qids,index=parent['index']);manifest['query_repos'][repo]={'queries':len(set(qids)),'rows':len(qids),'parent_features_sha256':sha(PARENT/f'{repo}.npz'),'output_sha256':sha(OUT/f'{repo}.npz'),'query_ms':timings};(OUT/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'features_complete':repo,'rows':len(qids)}),flush=True);del owners,units,vectors,matrix,extra;gc.collect()
assert len(bindings)==800 and len(manifest['query_repos'])==16 and verify_frozen_source(ENGINE)==receipt;(OUT/'query-input-bindings.jsonl').write_text(''.join(json.dumps(row)+'\n'for row in bindings));manifest['query_input_bindings_sha256']=sha(OUT/'query-input-bindings.jsonl');manifest['query_encoder_calls']=len(query_cache);(OUT/'registration.json').write_text(json.dumps(manifest,indent=2))
