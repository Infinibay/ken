"""One real normal-API probe for every newly changed input among95Javaqueries."""
from pathlib import Path
import hashlib,json,os,resource,shutil,sqlite3,subprocess,sys,time
base=Path.cwd();clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');out=base/'output/development/invocation-api-probe-v312';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();write=lambda p,v:p.write_text(json.dumps(v,indent=2)+'\n')
if len(sys.argv)==1:
 out.mkdir(exist_ok=False);frozen=out/'engine';frozen.mkdir();pins={}
 for name in json.loads((base/'output/frozen/repoqa-final-cpp-v296/SOURCE-MANIFEST.json').read_text())['files']:
  target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(clean/name,target);pins[name]=sha(target)
 write(frozen/'SOURCE-MANIFEST.json',{'files':pins,'scope':'Current source after invocation family/type-only annotation, unchanged models; capture before full-suite close.'})
 replay=base/'output/analysis/prior-java-invocation-v308';reg=json.loads((replay/'registration.json').read_text());assert sha(replay/'predictions.jsonl')==reg['predictions_sha256'];changed={r['id'] for r in map(json.loads,(replay/'predictions.jsonl').read_text().splitlines()) if r['changed_input']};prior=base/'output/development/prior-java-regression-v276';requests=[r for r in map(json.loads,(prior/'repoqa-requests.jsonl').read_text().splitlines()) if r['id'] in changed];assert len(requests)==1;request=requests[0];request['root']=str(out/'project');write(out/'request.json',request);source=json.loads((prior/'repoqa-sources.json').read_text())[request['repo_id']];write(out/'source.json',source)
 write(out/'registration.json',{'engine_manifest_sha256':sha(frozen/'SOURCE-MANIFEST.json'),'request_sha256':sha(out/'request.json'),'source_sha256':sha(out/'source.json'),'producer_sha256':sha(Path(__file__)),'selection':'Every changed invocation input in the full closed95case replay; no labels/hits used for worker selection.','source_index':'Owned copy of the original prepared source index; Java/Kotlin parser code unchanged. Ranking-policy change needs no source reindex. Later validate exact native10membership against fresh migration V276.','reserve':'CLOSED','normal_api':True,'MCP_transport':False})
 env=os.environ|{'PYTHONPATH':str(frozen/'src'),'PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1','HF_HUB_CACHE':str(base/'output/models/portable-public-hub-v143'),'KEN_CACHE_DIR':str(base/'output/models/portable-public-prepared-v143'),'KEN_INDEX_WORKERS':'0','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','OMP_NUM_THREADS':'1'};raise SystemExit(subprocess.run([sys.executable,str(Path(__file__).resolve()),'worker'],env=env).returncode)
reg=json.loads((out/'registration.json').read_text());assert sha(out/'engine/SOURCE-MANIFEST.json')==reg['engine_manifest_sha256']
for name,digest in json.loads((out/'engine/SOURCE-MANIFEST.json').read_text())['files'].items():assert sha(out/'engine'/name)==digest
request=json.loads((out/'request.json').read_text());source=json.loads((out/'source.json').read_text());assert sha(out/'request.json')==reg['request_sha256'] and sha(out/'source.json')==reg['source_sha256'];root=Path(request['root']);root.mkdir(exist_ok=False);original=Path(source['original_root'])
for name,digest in source['source_pins'].items():
 path=original/name;assert sha(path)==digest;target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
(root/'.ken/search-context').mkdir(parents=True)
for source_db,target in [(original/'.ken/ken.db',root/'.ken/ken.db'),(original/'.ken/search-context/vectors.db',root/'.ken/search-context/vectors.db')]:
 with sqlite3.connect('file:'+str(source_db)+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)
if (original/'.ken/vectors').is_dir():shutil.copytree(original/'.ken/vectors',root/'.ken/vectors')
import ken
assert Path(ken.__file__).resolve().parents[2]==out/'engine'
from ken.retrieval.public import find_best,render
from ken.retrieval.connections import project_connection
from ken.retrieval.best_resources import default_resources
with project_connection(root) as conn:
 warmup=find_best(conn,root,'find code that prepares a value',scope='symbols',piece_kind='symbol');assert warmup.get('ok') is not False;started=time.perf_counter();response=find_best(conn,root,request['query'],scope=request['scope'],piece_kind=request['piece_kind'],limit=10,max_chars=12000);elapsed=(time.perf_counter()-started)*1000;assert response.get('ok') is not False and len(response['results'])==10;compact=render(response)
resources=default_resources();assert list(resources.neural.providers)==list(resources.context.providers)==['CPUExecutionProvider'];assert resources.neural._max_tokens==1024 and not any(n in sys.modules for n in ('torch','transformers'));write(out/'response.json',response);write(out/'cost.json',{'elapsed_ms':elapsed,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','providers':list(resources.neural.providers),'reranker_tokens':1024});(out/'response.txt').write_text(compact)
for name,digest in source['source_pins'].items():assert sha(root/name)==digest
write(out/'closure.json',{'all_outputs_closed':True,'queries':1,'pins':{p.name:sha(p) for p in out.iterdir() if p.is_file()},'reserve':'CLOSED','labels_in_worker':False});shutil.rmtree(root/'.ken');print(json.dumps({'closed':1,'elapsed_ms':elapsed}),flush=True)
