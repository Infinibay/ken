"""Append one fixed source-only25 projection to ALL original251 public rows."""
import argparse,gc,hashlib,itertools,json,resource,sqlite3,sys,time
from pathlib import Path
import ken
import numpy as np
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.retrieval.evidence_features import _coverage
from ken.retrieval.owner_ranking import EvidenceReranker
from lexical_context_catalog import load_context_catalog
from lexical_context_features import FEATURES,context_texts,lexical_context_features
from replay import load_pools
from replay_parent import validate_replay_parent

def sha(path):
 with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def array_sha(value):return hashlib.sha256(memoryview(np.ascontiguousarray(value)).cast('B')).hexdigest()

parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
receipt=verify_frozen_source(E);assert receipt=='d0279cd002a743cc2f824aa78fbd44e326487b0e575a1fc53914588a388d3e99'
P=R/'output/analysis/c-source-reindex-v66c';F=R/'output/analysis/context-views-features-source7-v69';C=R/'output/analysis/lexical-source-v95';S=R/'output/analysis/lexical-projections-v96'
pins={P/'registration.json':'17ac3c3c26170f8929b2cc1a21fe9a7e036603452929c73a435a07e88628dd6a',F/'registration.json':'74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2',C/'registration.json':'5c5c1d79ca3d4310b80c3dd4f9f1c5936dbf3cb452be8b69fe4919b953781581',S/'registration.json':'b7d283d924468a8d14833dc66dd94f9709ea1cda060d3e414fd180492f6cf285'}
assert all(sha(p)==h for p,h in pins.items())
source=json.loads((S/'registration.json').read_text());parent=json.loads((P/'registration.json').read_text());prior=json.loads((F/'registration.json').read_text())
roots_path=E/'experiments/search-engine/datasets/roots-development.json';roots={k:Path(v)for k,v in json.loads(roots_path.read_text()).items()}
assert source['complete']and source['engine_receipt']==receipt and len(source['repos'])==16 and set(roots)==set(source['repos'])==set(parent['source_repos'])
assert sum(v['contexts']for v in source['repos'].values())==36194
assert all(sha(p)==h for p,h in source['inputs'].items())
for repo,root in roots.items():assert all(sha(root/p)==h for p,h in parent['source_repos'][repo]['file_hashes'].items())
# All16 source projection tables are pinned before any public query is read.
for repo in sorted(roots):assert sha(S/(repo+'.db'))==source['repos'][repo]['database_sha256']
parent_bindings=validate_replay_parent(F,P);assert len(parent_bindings)==51
static_path=R/'output/models/static-comparison-registration.json';assert sha(static_path)=='e7127a2c645b75c493de9dd8826d9ecb8078dc7c758a86ca49f97b84f68aed1b'
registration=next(v for v in json.loads(static_path.read_text())if v['model_id']=='minishlab/potion-code-16M-v2')
words=StaticEmbeddingControl(Path(registration['root']),registration)
coverage=lambda query,documents,fields:_coverage(query,documents,fields,encoder=words,stem_words=EvidenceReranker.stem_words)
requests={};bindings={str(p):h for p,h in pins.items()};bindings.update(source['inputs']);bindings[str(static_path)]=sha(static_path)
for path in sorted((P/'requests').glob('*.jsonl')):
 bindings[str(path)]=sha(path)
 for row in map(json.loads,path.read_text().splitlines()):
  assert row['id']not in requests;assert set(row)=={'id','repo_id','request'};requests[row['id']]=row
bindings.update(parent_bindings)
assert len(requests)==400 and all(sum(r['repo_id']==repo for r in requests.values())==25 for repo in roots)
expanded={};bindings[str(P/'candidates.jsonl')]=sha(P/'candidates.jsonl')
with (P/'candidates.jsonl').open()as stream:
 for row in map(json.loads,stream):
  assert row['id']not in expanded;assert isinstance(row['expanded_query'],str);expanded[row['id']]=row['expanded_query']
assert expanded.keys()==requests.keys()
names=(*prior['features'],*FEATURES);assert len(prior['features'])==251 and len(names)==276
O=args.output;O.mkdir(exist_ok=False)
manifest={'scope':'ALL400 original public pools; original251bitexact+fixed25lexicalsource features; complete source96 first, no labels/cases/references/fit','script_sha256':sha(__file__),'engine_receipt':receipt,'features':names,'inputs':bindings,'source_registration_sha256':sha(S/'registration.json'),'source_phase_complete':True,'repos':{},'groups':{},'exact_bypass_ids':[]}
(O/'registration.json').write_text(json.dumps(manifest,indent=2));total=0
for repo in sorted(roots):
 started=time.perf_counter();index=P/'indices'/(repo+'.db')
 catalog=load_context_catalog(folder=C,registration_sha256=pins[C/'registration.json'],engine_receipt='13fec1b8eaf9e6d017d72d61c7ddaee61af83a9a9d8776be34354918b5734556',repo=repo,index=index)
 bindings.update(catalog.receipts);projection=S/(repo+'.db');bindings[str(projection)]=sha(projection)
 # Check literal fields against every authenticated context, not just retrieved candidates.
 db=sqlite3.connect(projection.resolve().as_uri()+'?mode=ro',uri=True);checked=0
 for entity,context in catalog.contexts.items():
  identity=json.dumps({'path':entity.path,**entity.to_dict()},sort_keys=True,separators=(',',':'))
  stored=db.execute('SELECT source_hash,generation,full,nested,full_sha256,nested_sha256 FROM projections WHERE entity=?',(identity,)).fetchone();fields=context_texts(context)
  assert stored==(context.source_hash,context.generation,fields['lexical_full'],fields['lexical_nested'],hashlib.sha256(fields['lexical_full'].encode()).hexdigest(),hashlib.sha256(fields['lexical_nested'].encode()).hexdigest());checked+=1
 assert checked==db.execute('SELECT count(*) FROM projections').fetchone()[0]==source['repos'][repo]['contexts'];db.close()
 old_path=F/(repo+'.npz');assert sha(old_path)==prior['query_repos'][repo]['output_sha256'];bindings[str(old_path)]=sha(old_path)
 with np.load(old_path)as loaded:old={k:loaded[k]for k in('x','qid','index')}
 assert old['x'].shape==(len(old['qid']),251)and np.isfinite(old['x']).all()
 pools=load_pools(P,requests,repositories=[repo]);addition=np.zeros((len(old['qid']),25));seen=set();available=0
 for qid,indices in itertools.groupby(range(len(old['qid'])),key=lambda i:str(old['qid'][i])):
  selected=np.array(list(indices));pool=pools[qid];assert qid not in seen and requests[qid]['repo_id']==repo;seen.add(qid)
  assert len(selected)==len(pool)and np.array_equal(old['index'][selected],np.arange(len(pool)))
  exact=len(pool)==1 and bool(pool[0].signals.get('exact'))
  if exact:manifest['exact_bypass_ids'].append(qid);context_count=0
  else:
   contexts=[catalog.get(c.entity,source_hash=c.passages[0].source_hash,source_generation=catalog.source_generation)for c in pool]
   addition[selected]=lexical_context_features(expanded[qid],contexts,coverage=coverage);context_count=sum(c is not None for c in contexts);available+=context_count
  manifest['groups'][qid]={'repo':repo,'rows':len(selected),'exact_bypass':exact,'contexts':context_count,'original251_sha256':array_sha(old['x'][selected]),'new25_sha256':array_sha(addition[selected]),'expanded_query_sha256':hashlib.sha256(expanded[qid].encode()).hexdigest()}
 assert len(seen)==25 and seen==set(pools)
 numeric=np.column_stack((old['x'],addition));assert numeric.shape==(len(old['qid']),276)and np.array_equal(numeric[:,:251],old['x'])and np.isfinite(numeric).all()
 destination=O/(repo+'.npz');np.savez_compressed(destination,x=numeric,qid=old['qid'],index=old['index'])
 total+=len(numeric);manifest['repos'][repo]={'queries':25,'rows':len(numeric),'available_context_rows':available,'output_sha256':sha(destination),'ms':(time.perf_counter()-started)*1000}
 (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'prepared_repository':repo,**manifest['repos'][repo]}),flush=True)
 del pools,pool,old,numeric,addition,catalog;gc.collect()
assert total==167360 and len(manifest['groups'])==400 and len(manifest['exact_bypass_ids'])==37
assert all(sha(p)==h for p,h in bindings.items())and verify_frozen_source(E)==receipt
assert parent_bindings==validate_replay_parent(F,P)
for repo,root in roots.items():assert all(sha(root/p)==h for p,h in parent['source_repos'][repo]['file_hashes'].items())
assert not any(name in sys.modules for name in('torch','transformers','onnxruntime','lightgbm','ctranslate2'))
manifest.update(complete=True,total_rows=total,peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
