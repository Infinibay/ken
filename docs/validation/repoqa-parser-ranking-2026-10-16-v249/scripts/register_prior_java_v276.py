"""Register unchanged prior public Java requests affected by constructor eligibility."""
from pathlib import Path
import hashlib,json,shutil,sqlite3,subprocess,sys
base=Path.cwd();clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');frozen=base/'output/frozen/prior-java-current-v276';out=base/'output/development/prior-java-regression-v276';producer=Path(__file__).with_name('capture_variant_v255.py')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
manifest=json.loads((base/'output/frozen/repoqa-cpp-contracts-v252/SOURCE-MANIFEST.json').read_text());frozen.mkdir(exist_ok=False);pins={}
for name in manifest['files']:
 source=clean/name;assert source.is_file(),name;target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);pins[name]=sha(target)
write(frozen/'SOURCE-MANIFEST.json',{'files':pins,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=clean,text=True).strip(),'source_root':str(clean),'scope':'current production source, models unchanged; code checkpoint before prior Java regression'})
out.mkdir(exist_ok=False);requests=[];sources={};capture_pins={};query_pins={}
for cohort in ('original','symbols'):
 run=base/f'output/development/public-bounded-symbol-ranking-v214-{cohort}';lock=json.loads((run/'lock.json').read_text());reg=json.loads((run/'capture/registration.json').read_text());assert reg['lock_sha256']==sha(run/'lock.json')
 cases=Path(lock['public_cases']);assert sha(cases)==lock['input_pins'][str(cases)];query_pins[str(cases)]=sha(cases);capture_pins[str(run/'capture/registration.json')]=sha(run/'capture/registration.json')
 for case in map(json.loads,cases.read_text().splitlines()):
  if case['repo_id'] not in ('commons-csv','junit5'):continue
  repo=case['repo_id'];requests.append({'id':case['id'],'repo_id':repo,'root':str(out/'projects'/repo),'query':case['query'],'scope':'symbols' if case['target_kind'] in ('class','symbol') else 'files','piece_kind':case['target_kind'],'language':case['language'],'cohort':'original200' if cohort=='original' else 'new_symbol200'})
  if repo not in sources:
   original=Path(lock['roots'][repo]);source_pins={}
   with sqlite3.connect('file:'+str(original/'.ken/ken.db')+'?mode=ro',uri=True) as conn:
    for name,blake in conn.execute('SELECT path,content_hash FROM ci_files'):
     path=original/name;assert hashlib.blake2b(path.read_bytes(),digest_size=32).digest()==blake,name;source_pins[name]=sha(path)
   sources[repo]={'original_root':str(original),'source_pins':source_pins}
assert len(requests)==95 and len({r['id'] for r in requests})==95
(out/'repoqa-requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests));write(out/'repoqa-sources.json',sources)
registration={'engine':str(frozen),'engine_manifest_sha256':sha(frozen/'SOURCE-MANIFEST.json'),'requests_sha256':sha(out/'repoqa-requests.jsonl'),'sources_sha256':sha(out/'repoqa-sources.json'),'queries':95,'groups':2,'normal_api':True,'MCP_transport':False,'same_find_best_engine_as_MCP':True,'models_and_ranking_weights_unchanged':True,'private_reserve':'CLOSED','capture_stages':False,'serial_after_capture':str(base/'output/development/repoqa-rust-candidate-pool-v274/capture/closure.json'),'producer_sha256':sha(producer),'old_capture_registration_pins':capture_pins,'public_case_pins':query_pins,'source_scope':'Every original indexed physical file, byte-identical to existing CI content_hash; owned copied SQLite and source vectors. Only two prior repositories contain constructor/destructor owners or ambiguous headers.'}
write(out/'registration.json',registration);print(json.dumps({'registered':str(out),'queries':95,'sha256':sha(out/'registration.json'),'serial_after':registration['serial_after_capture']}),flush=True)
raise SystemExit(subprocess.run([sys.executable,str(producer),'--out',str(out)]).returncode)
