"""Prove the new unsupported invocation family preserves the200closed CPP/Rust orders."""
from pathlib import Path
import dataclasses,hashlib,importlib.util,json,sys
base=Path.cwd();clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');sys.path.insert(0,str(clean/'src'))
from ken.retrieval.model import EntityKey,SearchRequest
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.source_operations import OperationWitnesses
from ken.retrieval.symbol_requirements import requirements,prefer_operations
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();old_path=base/'output/frozen/repoqa-final-cpp-v296/src/ken/retrieval/symbol_requirements.py';spec=importlib.util.spec_from_file_location('legacy_v315',old_path);old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old);rows=[];pins={};observer=OperationWitnesses(SourceCatalog(base,{}))
for language,run in [('cpp',base/'output/development/repoqa-cpp-coverage-v246'),('rust',base/'output/development/repoqa-rust-coverage-v239')]:
 requests=[json.loads(x) for x in (run/'repoqa-requests.jsonl').read_text().splitlines()];reg=json.loads((run/'registration.json').read_text());assert sha(run/'repoqa-requests.jsonl')==reg['requests_sha256'];closure=json.loads((run/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100;pins[str(run/'capture/closure.json')]=sha(run/'capture/closure.json');answers={}
 for name,digest in closure['response_pins'].items():
  if name.endswith('/responses.json'):
   path=run/'capture'/name;assert sha(path)==digest;answers.update({r['id']:r for r in json.loads(path.read_text())})
 assert len(answers)==100
 for request in requests:
  r=SearchRequest(request['query'],target='symbol',piece_kind='symbol');a,b=old.requirements(r),requirements(r);assert a.test_case==b.test_case and a.operators==b.operators and b.operations in (a.operations,a.operations|{'invocation'});items=answers[request['id']]['results'];assert len(items)==10
  facts=[observer.for_owner(EntityKey(path=i['path'],**i['entity'])) for i in items];assert not any(facts),'new supported grammar requires a fresh experiment, not an equivalence claim';order=list(range(len(items)));assert prefer_operations(a.operations,facts,order)==prefer_operations(b.operations,facts,order)==order
  rows.append({'id':request['id'],'language':language,'before_operations':sorted(a.operations),'after_operations':sorted(b.operations),'candidates':len(items),'all_witnesses_unsupported_empty':True,'stable_order_preserved':True})
assert len(rows)==200;out={'queries':200,'results':sum(r['candidates'] for r in rows),'changed_requirement_inputs':{language:sum(r['language']==language and r['before_operations']!=r['after_operations'] for r in rows) for language in ('cpp','rust')},'stable_orders_preserved':True,'input_closure_pins':pins,'new_policy_sources':{name:sha(clean/'src/ken/retrieval'/name) for name in ('source_operations.py','symbol_requirements.py','symbol_ranking.py')},'before_requirements_sha256':sha(old_path),'producer_sha256':sha(Path(__file__)),'rows':rows,'reserve':'CLOSED','interpretation':'Deterministic policy equivalence, no inference/Gold/latency capture. Unsupported grammar returns empty observations independently of catalog state; empty observations mean unknown, not absence of source calls. Current old/new preferences are constant false (or no requirement), so preserve ANY candidate order and membership. All200real closed result paths exercise that fastpath; operators/test/path policies and native/neural inputs are unchanged. CPP prior69/88quality assembly and Rust59/90parser-only capture therefore retain their quality scope, not a new full200normalAPImeasurement.'};(base/'output/analysis/repoqa-diagnosis-v236/invocation-language-equivalence-v315.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='rows'},indent=2))
