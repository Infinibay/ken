"""Register full-contract-only comparison after source-cache closure; no labels."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
base=Path.cwd();source=base/'output/development/repoqa-cpp-coverage-v246';out=base/'output/development/repoqa-cpp-contracts-v255'
cache_run=base/'output/analysis/repoqa-source-caches-v251';engine=base/'output/frozen/repoqa-cpp-contracts-v252';producer=Path(__file__).with_name('capture_variant_v255.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
producer_pin=sha(producer)
while not (cache_run/'closure.json').is_file():time.sleep(5)
caches=json.loads((cache_run/'closure.json').read_text());assert caches['source_only'] and caches['no_query_or_relevance_cache']
assert sha(engine/'SOURCE-MANIFEST.json')=='dd27e9bbe6756a3a38931796db98c0c3f829c06b996ea888c43c099122a2681e'
out.mkdir(exist_ok=False)
requests=[json.loads(x) for x in (source/'repoqa-requests.jsonl').read_text().splitlines()];sources=json.loads((source/'repoqa-sources.json').read_text())
for request in requests:request['root']=str(out/'projects'/request['repo_id'])
for group,cache in caches['caches'].items():
 assert sha(Path(cache['path']))==cache['sha256'];sources[group].update(context_cache_source=cache['path'],context_cache_sha256=cache['sha256'])
(out/'repoqa-requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests))
(out/'repoqa-sources.json').write_text(json.dumps(sources,indent=2)+'\n')
registration=json.loads((source/'registration.json').read_text());registration.update(engine=str(engine),engine_manifest_sha256=sha(engine/'SOURCE-MANIFEST.json'),requests_sha256=sha(out/'repoqa-requests.jsonl'),sources_sha256=sha(out/'repoqa-sources.json'),serial_after_capture=str(base/'output/analysis/repoqa-rust-stages-v251/capture/closure.json'),capture_stages=False,change='Complete C++ signatures, docstrings and scoped implementation boundaries; identical models and ranker.',comparison_capture=str(source),source_cache_closure_sha256=sha(cache_run/'closure.json'),producer_sha256=producer_pin)
(out/'registration.json').write_text(json.dumps(registration,indent=2)+'\n')
print(json.dumps({'registered':str(out),'registration_sha256':sha(out/'registration.json'),'serial_after':registration['serial_after_capture']}),flush=True)
assert sha(producer)==producer_pin
raise SystemExit(subprocess.run([sys.executable,str(producer),'--out',str(out)]).returncode)
