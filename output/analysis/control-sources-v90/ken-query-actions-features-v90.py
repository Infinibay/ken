"""Collect unchanged source7 word roles first; append only grammatical-query evidence."""
import collections,gc,hashlib,itertools,json,resource,sqlite3,sys,time
from functools import partial
from importlib.metadata import version
from pathlib import Path
import numpy as np
import ken
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');E=Path(ken.__file__).resolve().parents[2];sys.path.insert(0,str(E/'experiments/search-engine'))
from action_evidence import FEATURES,action_evidence
from query_actions import extract_actions
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.retrieval.description import describe_owner
from ken.retrieval.evidence_features import _coverage
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.storage import load_passage_map
from ken.retrieval.tokenization import code_terms
O=R/'output/analysis/query-actions-features-v90';O.mkdir(exist_ok=False);(O/'source').mkdir()
P=R/'output/analysis/c-source-reindex-v66c';F=R/'output/analysis/context-views-features-source7-v69';V=R/'output/analysis/context-views-source7-v69';M=R/'output/models/query-actions-v90';Q=R/'output/analysis/query-actions-diagnostic-v90'
def sha(path):
 with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
key=lambda entity:json.dumps({'path':entity.path,**entity.to_dict()},sort_keys=True,separators=(',',':'))
receipt=verify_frozen_source(E);assert receipt=='d0fa6e6e3b80eb432d19b73449211e7cee26df235b976e59f91f7594c43f6259'
assert sha(F/'registration.json')=='74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
assert sha(V/'registration.json')=='d4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
source=json.loads((P/'registration.json').read_text());parent=json.loads((F/'registration.json').read_text());views=json.loads((V/'registration.json').read_text());roots={k:Path(v)for k,v in json.loads((R/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(roots)==len(source['source_repos'])==16
inputs={str(p):sha(p)for p in(P/'registration.json',F/'registration.json',V/'registration.json',M/'registration.json',E/'experiments/search-engine/cpu-query-actions-v90.md',E/'experiments/search-engine/cpu-query-actions-v90-supplement.md',E/'experiments/search-engine/query_actions.py',E/'experiments/search-engine/action_evidence.py')}
manifest={'scope':'Source-only word roles ALL16/50967 before requests; same original251 prefix plus33 grammatical-action fields, no90fitting/quality/private','engine_receipt':receipt,'controller_sha256':sha(__file__),'inputs':inputs,'extra_features':FEATURES,'source_repos':{},'query_repos':{},'source_phase_complete':False}
for repo,root in sorted(roots.items()):
 meta=source['source_repos'][repo];assert all(sha(root/path)==digest for path,digest in meta['file_hashes'].items())
 index=P/'indices'/(repo+'.db');assert sha(index)==meta['new_source_index_sha256'];inputs[str(index)]=sha(index)
 conn=sqlite3.connect(f'file:{index}?mode=ro',uri=True);conn.row_factory=sqlite3.Row
 groups=collections.defaultdict(list)
 for p in load_passage_map(conn).values():groups[p.entity].append(p)
 conn.close();assert len(groups)==meta['owners']==views['source_repos'][repo]['owners']
 path=O/'source'/(repo+'.db');db=sqlite3.connect(path);db.execute('CREATE TABLE words(entity TEXT PRIMARY KEY, source_hash TEXT, fields_json TEXT)');totals=collections.Counter()
 for entity,passages in sorted(groups.items(),key=lambda item:key(item[0])):
  owner=describe_owner(passages);assert owner.source_hash==meta['file_hashes'][entity.path]
  fields={name:owner.fields[name]for name in('identity','signature','documentation','path','implementation','comments','executable','calls','returns')};fields['all']='\n'.join(fields.values())
  words={name:code_terms(fields[name],limit=4096)for name in('executable','calls','returns','all')}
  db.execute('INSERT INTO words VALUES (?,?,?)',(key(entity),owner.source_hash,json.dumps(words,separators=(',',':'))));totals.update({name:len(value)for name,value in words.items()})
 db.commit();db.close();assert sha(index)==inputs[str(index)]
 manifest['source_repos'][repo]={'owners':len(groups),'indexed_files':len(meta['file_hashes']),'word_counts':dict(totals),'source_sha256':sha(index),'word_database_sha256':sha(path)}
 (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'source_complete':repo,'owners':len(groups)}),flush=True);del groups,passages,owner,fields,words;gc.collect()
assert sum(m['owners']for m in manifest['source_repos'].values())==50967 and sum(m['indexed_files']for m in manifest['source_repos'].values())==6314
manifest['source_phase_complete']=True;(O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'all_source_complete':True,'owners':50967,'files':6314}),flush=True)
# Only now acquire any requests or grammatical-query records.
queries_path=R/'output/analysis/es-en-control-v16/queries.jsonl';diagnostic=json.loads((Q/'registration.json').read_text());assert diagnostic['complete']and sha(Q/'queries.jsonl')==diagnostic['output_sha256']
assert all(sha(p)==h for p,h in diagnostic['inputs'].items())
queries={r['id']:r for r in map(json.loads,queries_path.read_text().splitlines())};recorded={r['id']:r for r in map(json.loads,(Q/'queries.jsonl').read_text().splitlines())};assert len(queries)==len(recorded)==400
for p in(queries_path,Q/'registration.json',Q/'queries.jsonl',R/'output/models/static-comparison-registration.json'):inputs[str(p)]=sha(p)
parent_bindings=validate_replay_parent(F,P);assert len(parent_bindings)==51;manifest['parent_bindings']=parent_bindings
model=json.loads((M/'registration.json').read_text());assert all(sha(M/p)==h for p,h in model['files'].items());assert version('nltk')=='3.9.2'
from nltk.tag import PerceptronTagger
from nltk.tokenize import TreebankWordTokenizer
tagger=PerceptronTagger(lang='eng',loc=str(M/'averaged_perceptron_tagger_eng'));tokenizer=TreebankWordTokenizer()
registration=next(r for r in json.loads((R/'output/models/static-comparison-registration.json').read_text())if r['model_id']=='minishlab/potion-code-16M-v2');words_encoder=StaticEmbeddingControl(Path(registration['root']),registration);manifest['static_encoder']=words_encoder.identity
coverage=partial(_coverage,encoder=words_encoder,stem_words=EvidenceReranker.stem_words)
requests={}
for p in sorted((P/'requests').glob('*.jsonl')):
 for row in map(json.loads,p.read_text().splitlines()):assert row['id']not in requests;requests[row['id']]=row
assert requests.keys()==queries.keys()==recorded.keys()
for repo in sorted(roots):
 source_path=O/'source'/(repo+'.db');assert sha(source_path)==manifest['source_repos'][repo]['word_database_sha256']
 db=sqlite3.connect(f'file:{source_path}?mode=ro',uri=True);descriptions={identity:(digest,json.loads(data))for identity,digest,data in db.execute('SELECT entity,source_hash,fields_json FROM words')};db.close()
 path=F/(repo+'.npz');assert sha(path)==parent['query_repos'][repo]['output_sha256'];inputs[str(path)]=sha(path)
 with np.load(path)as a:original={k:a[k]for k in('qid','index')}
 pools=load_pools(P,requests,repositories=[repo]);blocks=[];qids=[];indexes=[];metadata=[]
 for qid,items in itertools.groupby(range(len(original['qid'])),key=lambda i:str(original['qid'][i])):
  rows=np.array(list(items));pool=pools[qid];assert len(pool)==len(rows)and np.array_equal(original['index'][rows],np.arange(len(pool)))
  query=queries[qid];assert query['query']==requests[qid]['request']['query']and query['expanded']==recorded[qid]['query']
  actions=extract_actions(query['expanded'],tokenize=tokenizer.tokenize,tag=tagger.tag);assert tuple(recorded[qid]['tokens'])==actions.tokens and tuple(recorded[qid]['actions'])==actions.actions
  documents=[]
  for candidate in pool:
   digest,fields=descriptions[key(candidate.entity)];assert digest==candidate.passages[0].source_hash;documents.append(fields)
  exact=bool(len(pool)==1 and pool[0].signals.get('exact'))
  begin=time.perf_counter();block=np.zeros((len(pool),len(FEATURES)))if exact else action_evidence(actions,documents,coverage=coverage);elapsed=(time.perf_counter()-begin)*1000
  assert block.shape==(len(pool),33)and np.isfinite(block).all();blocks.append(block);qids.extend([qid]*len(pool));indexes.extend(range(len(pool)))
  metadata.append({'id':qid,'actions':actions.actions,'action_tokens':len(actions.actions),'tokens':len(actions.tokens),'exact_bypass':exact,'rows':len(pool),'elapsed_ms':elapsed});print(json.dumps({'features_complete':qid,'rows':len(pool),'actions':len(actions.actions)}),flush=True)
 destination=O/(repo+'.npz');np.savez(destination,x=np.concatenate(blocks),qid=np.array(qids),index=np.array(indexes));manifest['query_repos'][repo]={'rows':len(qids),'queries':metadata,'output_sha256':sha(destination),'parent251_sha256':sha(path)}
 (O/'registration.json').write_text(json.dumps(manifest,indent=2));del pools,pool,descriptions,documents,blocks,original;gc.collect()
assert len(manifest['query_repos'])==16 and sum(m['rows']for m in manifest['query_repos'].values())==167360
assert sum(len(m['queries'])for m in manifest['query_repos'].values())==400
assert all(sha(p)==h for p,h in inputs.items())and parent_bindings==validate_replay_parent(F,P)and verify_frozen_source(E)==receipt
assert all(sha(roots[repo]/p)==h for repo in roots for p,h in source['source_repos'][repo]['file_hashes'].items())and all(sha(M/p)==h for p,h in model['files'].items())
assert not any(k in sys.modules for k in('torch','transformers','sentence_transformers'))
manifest['complete']=True;manifest['peak_rss_native_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;manifest['runtime']={p:version(p)for p in('numpy','nltk','model2vec','tokenizers','snowballstemmer')};(O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'complete':True,'rows':167360,'extra_features':33,'peak_rss_native_bytes':manifest['peak_rss_native_bytes']}),flush=True)
