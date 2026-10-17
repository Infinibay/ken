"""Retry the identical100-case experiment with supported neural-call chunking."""
from pathlib import Path
from collections import Counter
import hashlib,json,subprocess,sys
base=Path.cwd();source=base/'output/development/repoqa-rust-candidate-pool-v274';out=base/'output/development/repoqa-rust-candidate-pool-v299';folder=Path(__file__).parent;old_producer=folder/'capture_candidate_pool_v274.py';producer=folder/'capture_candidate_pool_v299.py';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();closure=json.loads((source/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['response_pins'].items():assert sha(source/'capture'/name)==digest
errors=Counter(r.get('error') for path in (source/'capture').glob('*/responses.json') for r in json.loads(path.read_text()));assert errors=={'ValueError: reranking is limited to the native top10':100}
text=old_producer.read_text();before='    scores,details=resources.neural.score(expanded,texts)';after='''    scores=[];details={'token_ms':0.,'inference_ms':0.,'truncated_documents':0,'pair_tokens':[],'api_calls':0}
    for start in range(0,len(texts),10):
        chunk,observed=resources.neural.score(expanded,texts[start:start+10]);scores.extend(chunk)
        for name in ('token_ms','inference_ms','truncated_documents'):details[name]+=observed[name]
        details['pair_tokens'].extend(observed['pair_tokens']);details['api_calls']+=1
        if 'pad_id' in observed:details['pad_id']=observed['pad_id']
    assert len(scores)==len(texts)<=20 and details['api_calls']<=2''';assert text.count(before)==1 and not producer.exists();producer.write_text(text.replace(before,after))
# Source-level fake scorer checks the sole changed adapter before real queries/models.
import ast
module=ast.parse(producer.read_text());function=next(node for node in module.body if isinstance(node,ast.FunctionDef) and node.name=='search_pool');segment=ast.parse('def chunk_check(resources,expanded,texts):\n'+after+'\n    return scores,details\n');scope={};exec(compile(segment,'chunk_adapter_smoke','exec'),scope)
from types import SimpleNamespace
class Fake:
 def __init__(self):self.calls=[]
 def score(self,query,texts):
  assert len(texts)<=10;self.calls.append(len(texts));return [float(x) for x in texts],{'token_ms':1.,'inference_ms':2.,'truncated_documents':0,'pair_tokens':[7]*len(texts),'pad_id':0}
for size in (1,10,11,20):
 fake=Fake();scores,details=scope['chunk_check'](SimpleNamespace(neural=fake),'query',[str(i) for i in range(size)]);assert scores==list(map(float,range(size))) and sum(fake.calls)==size and len(details['pair_tokens'])==size and details['api_calls']==len(fake.calls)
out.mkdir(exist_ok=False);requests=[json.loads(x) for x in (source/'repoqa-requests.jsonl').read_text().splitlines()];assert len(requests)==100
for row in requests:row['root']=str(out/'projects'/row['repo_id'])
(out/'repoqa-requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests));(out/'repoqa-sources.json').write_bytes((source/'repoqa-sources.json').read_bytes());(out/'native-code-logits.json').write_bytes((source/'native-code-logits.json').read_bytes());reg=json.loads((source/'registration.json').read_text());reg.update(requests_sha256=sha(out/'repoqa-requests.jsonl'),native_code_scores=str(out/'native-code-logits.json'),native_code_scores_sha256=sha(out/'native-code-logits.json'),producer_sha256=sha(producer),serial_after_capture=str(base/'output/development/repoqa-final-cpp-guard-v296/capture/closure.json'),retry_of=str(source),failed_capture_closure_sha256=sha(source/'capture/closure.json'),only_retry_change='Same<=20independent pair scores, submitted in two supported calls<=10each instead of one unsupported call>10; same per-pair batch_size1, no truncation/pooling/model/selection changes.',adapter_smoke_sizes=[1,10,11,20]);(out/'registration.json').write_text(json.dumps(reg,indent=2)+'\n');failure={'queries':100,'query_errors':dict(errors),'results':0,'quality_claim':False,'failed_report_sha256':sha(source/'report.json'),'failed_closure_sha256':sha(source/'capture/closure.json'),'retry_registration_sha256':sha(out/'registration.json'),'reserve':'CLOSED','interpretation':'Preserve all100failed requests and0/100raw failed-attempt scores. This is a harness API-limit failure, not a model-selection result. Repeat all100 under an independently pinned infrastructure retry; do not salvage selected cases.'};(out/'infrastructure-retry-receipt.json').write_text(json.dumps(failure,indent=2)+'\n');print(json.dumps({'registered':str(out),'queries':100,'sha256':sha(out/'registration.json'),'serial_after':reg['serial_after_capture']}),flush=True);raise SystemExit(subprocess.run([sys.executable,str(producer),'--out',str(out)]).returncode)
