"""Register fixed Rust candidate-pool experiment, no labels or fitting."""
from pathlib import Path
import hashlib,json,subprocess,sys
base=Path.cwd();stage=base/'output/analysis/repoqa-rust-stages-v251';out=base/'output/development/repoqa-rust-candidate-pool-v274';producer=Path(__file__).with_name('capture_candidate_pool_v274.py');engine=base/'output/frozen/repoqa-rust-coverage-v238'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
closure=json.loads((stage/'capture/closure.json').read_text());assert closure['all_outputs_closed'] and closure['queries']==100
for name,digest in closure['response_pins'].items():assert sha(stage/'capture'/name)==digest
assert sha(engine/'SOURCE-MANIFEST.json')=='0a54033f12f4bb03c8f294b7a2416f79cd001c3748d42c56d8492eb9cb4f6c96'
out.mkdir(exist_ok=False);requests=[json.loads(x) for x in (stage/'repoqa-requests.jsonl').read_text().splitlines()];sources=json.loads((stage/'repoqa-sources.json').read_text())
for request in requests:request['root']=str(out/'projects'/request['repo_id'])
(out/'repoqa-requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in requests));(out/'repoqa-sources.json').write_text(json.dumps(sources,indent=2)+'\n')
scores={}
for group in sorted(sources):
 for observation in json.loads((stage/'capture'/group/'stages.json').read_text()):
  assert observation['normal_identities_reproduced'] and 'error' not in observation
  scores[observation['id']]={json.dumps([r['path'],r['entity']],ensure_ascii=False,sort_keys=True,separators=(',',':')):r['signals']['symbol_ranking']['code_score'] for r in observation['diagnostic_response']['results']}
assert len(scores)==100;(out/'native-code-logits.json').write_text(json.dumps(scores,indent=2)+'\n')
registration={'engine':str(engine),'engine_manifest_sha256':sha(engine/'SOURCE-MANIFEST.json'),'requests_sha256':sha(out/'repoqa-requests.jsonl'),'sources_sha256':sha(out/'repoqa-sources.json'),'queries':100,'groups':10,'normal_api':False,'experimental_source_response':True,'source_response_presentation':'unchanged SourceCatalog/present_cards/render with same10slots/12000chars','models_and_ranking_weights_unchanged':True,'private_reserve':'CLOSED','capture_stages':False,'serial_after_capture':str(base/'output/development/repoqa-cpp-contracts-v255/capture/closure.json'),'baseline_report_sha256':sha(base/'output/development/repoqa-core-v222/repoqa-report-v224.json'),'native_code_scores':str(out/'native-code-logits.json'),'native_code_scores_sha256':sha(out/'native-code-logits.json'),'logit_comparison_source_closure_sha256':sha(stage/'capture/closure.json'),'producer_sha256':sha(producer),'experiment_spec_sha256':sha(Path(__file__).parents[1]/'CANDIDATE-VIEW-EXPERIMENT-V274.md'),'policy':'native10+contextual10 unique eligible symbols, <=20 single-view neural pairs; unchanged explicit source preferences; return10. In-call native10 single-view control shares exact logits. No labels or learned thresholds.'}
(out/'registration.json').write_text(json.dumps(registration,indent=2)+'\n');print(json.dumps({'registered':str(out),'sha256':sha(out/'registration.json'),'serial_after':registration['serial_after_capture']}),flush=True)
raise SystemExit(subprocess.run([sys.executable,str(producer),'--out',str(out)]).returncode)
