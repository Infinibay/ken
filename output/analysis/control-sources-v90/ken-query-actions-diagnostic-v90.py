import hashlib,json,resource,sys,time
from pathlib import Path
import numpy as np
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');O=R/'output/analysis/query-actions-diagnostic-v90';O.mkdir(exist_ok=False);M=R/'output/models/query-actions-v90';sys.path.insert(0,str(R/'experiments/search-engine'))
from query_actions import extract_actions
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
registration=json.loads((M/'registration.json').read_text());assert all(sha(M/p)==h for p,h in registration['files'].items())
started=time.perf_counter()
from nltk.tag import PerceptronTagger
from nltk.tokenize import TreebankWordTokenizer
from importlib.metadata import version
assert version('nltk')=='3.9.2'
tagger=PerceptronTagger(lang='eng',loc=str(M/'averaged_perceptron_tagger_eng'));tokenizer=TreebankWordTokenizer();cold_ms=(time.perf_counter()-started)*1000
inputs=[R/'output/analysis/es-en-control-v16/queries.jsonl',M/'registration.json',R/'experiments/search-engine/cpu-query-actions-v90.md',R/'experiments/search-engine/query_actions.py',Path(__file__)]
bindings={str(p):sha(p)for p in inputs};queries=list(map(json.loads,inputs[0].read_text().splitlines()));assert len(queries)==len({q['id']for q in queries})==400
extract_actions('Find where a value is validated before returning it.',tokenize=tokenizer.tokenize,tag=tagger.tag)
rows=[];times=[]
for q in queries:
 begin=time.perf_counter();value=extract_actions(q['expanded'],tokenize=tokenizer.tokenize,tag=tagger.tag);times.append((time.perf_counter()-begin)*1000)
 rows.append({'id':q['id'],'query':q['expanded'],'tokens':value.tokens,'tags':tagger.tag(list(value.tokens)),'actions':value.actions})
for repeat in range(9):
 for q,before in zip(queries,rows,strict=True):
  begin=time.perf_counter();value=extract_actions(q['expanded'],tokenize=tokenizer.tokenize,tag=tagger.tag);times.append((time.perf_counter()-begin)*1000)
  assert tuple(before['tokens'])==value.tokens and tuple(before['actions'])==value.actions
(O/'queries.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n'for r in rows));np.save(O/'elapsed-ms.npy',np.asarray(times))
assert all(sha(p)==h for p,h in bindings.items())and all(sha(M/p)==h for p,h in registration['files'].items())
assert not any(k in sys.modules for k in('torch','transformers','sentence_transformers'))
summary={'scope':'Query-only grammatical diagnostic400/10repeats, no references/labels/candidates/encoder/fit/quality read','inputs':bindings,'nltk_version':version('nltk'),'cold_import_and_model_load_ms':cold_ms,'latency_ms':dict(zip(('p50','p95','p99','max'),map(float,np.percentile(times,[50,95,99,100])))),'peak_rss_native_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'queries':400,'no_actions':sum(not r['actions']for r in rows),'action_count_histogram':{str(n):sum(len(r['actions'])==n for r in rows)for n in sorted(set(len(r['actions'])for r in rows))},'output_sha256':sha(O/'queries.jsonl'),'elapsed_sha256':sha(O/'elapsed-ms.npy'),'complete':True}
(O/'registration.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2),flush=True)
