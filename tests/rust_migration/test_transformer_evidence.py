"""A sealed profile remains subject to independent semantics and identities."""
import copy,json
from pathlib import Path
import pytest
from test_transformer_compare import observations
from tools.rust_migration.transformer_evidence import profile_errors,source_identity
from tools.rust_migration.transformer_compare import request_policy
from tools.rust_migration.transformer_reference import CATALOG

def profile(tmp_path):
 source=tmp_path/'source';(source/'crates/ken-models/src').mkdir(parents=True)
 (source/'Cargo.toml').write_text('workspace');(source/'crates/ken-models/src/lib.rs').write_text('pub struct Judge;')
 original,actual=observations();files={'p/actual.json':json.dumps(actual).encode(),'p/inputs.json':b'{}','p/stderr.log':b'ken-transformer-module-/lib/libtorch_cpu.dylib'}
 core={'backend':'torch','core_version':'2.9.0','libraries':copy.deepcopy(actual['rows'][0]['preparation']['runtime']['libraries'])}
 row={'key':'macos|judge|Qwen/Qwen3-Reranker-0.6B|cpu|float32','directory':'p','source_files':source_identity(source),'runtime':copy.deepcopy(core),'host_binary':{'bytes':4,'sha256':'a'*64},'native_module':{'bytes':4,'sha256':'b'*64},'execution':{'native_exit':0,'outside_checkout':True,'native_children':[],'owned_after_exit':[],'native_sha256':'a'*64,'fixed_deadline_s':60,'elapsed_s':1,'execution_audit':True,'exec_attempts':None}}
 definition=next(m for m in json.loads(CATALOG.read_text())['models'] if m['name']==original['capture']['settings']['model_id'])
 inputs=request_policy(original)|{'model':definition,'runtime':{'format':'ken-native-transformer/1','backend':'torch','runtimes':[{'os':'macos','arch':'aarch64','core_version':'2.9.0','module':row['native_module'],'libraries':core['libraries']}]},'snapshot':'/models/Qwen--Qwen3-Reranker-0.6B/'+definition['assets']['revision'],'private_parent':'/private/owned','module':'/private/backend','core_root':'/cores/torch'}
 files['p/inputs.json']=json.dumps(inputs).encode()
 return source,original,files,core,row

def test_exact_profile_is_recompared_with_registered_core_and_current_source(tmp_path):
 source,original,files,core,row=profile(tmp_path)
 assert profile_errors(files,row,original,source,core)==[]

@pytest.mark.parametrize('change',['source','library','module','missing','score','token','device','deadline','timeout','child','ownership','audit'])
def test_resealed_false_profile_or_stale_runtime_or_source_is_rejected(tmp_path,change):
 source,original,files,core,row=profile(tmp_path)
 if change=='source':(source/'crates/ken-models/src/lib.rs').write_text('other')
 elif change=='library':row['runtime']['libraries']['lib/libtorch_cpu.dylib']['sha256']='d'*64
 elif change=='module':row['native_module']['sha256']='wrong'
 elif change=='missing':files.pop('p/actual.json')
 elif change in ('score','token','device'):
  value=json.loads(files['p/actual.json']);r=value['rows'][1]
  if change=='score':r['scores'][0]+=1
  elif change=='token':r['feeds'][0]['input_ids'][0][0]+=1
  else:r['preparation']['device']={'kind':'mps'}
  files['p/actual.json']=json.dumps(value).encode()
 elif change=='deadline':row['execution']['fixed_deadline_s']+=1
 elif change=='timeout':row['execution']['elapsed_s']=100000
 elif change=='child':row['execution']['native_children']=['python']
 elif change=='ownership':row['execution']['owned_after_exit']=['leaked-model']
 else:row['execution']['execution_audit']=False
 assert profile_errors(files,row,original,source,copy.deepcopy(core))


def gate_fixture():
 import hashlib
 from tools.rust_migration.transformer_sources import capacity_plan
 from tools.rust_migration.transformer_evidence import OWNERSHIP_CASES
 root=Path(__file__).resolve().parents[2];cores=json.loads((root/'tools/rust_migration/data/transformer-cores.json').read_text())['cores'];core=next(r for r in cores if (r['os'],r['arch'],r['backend'])==('linux','aarch64','torch'))
 models=json.loads((root/'crates/ken-models/resources/transformer-catalog.json').read_text())['models'];plans=[capacity_plan(m,core,module_bytes=10,acquire=True) for m in models];need=max(p['required_free_bytes'] for p in plans)
 capacity={'model_plans':plans,'next_phase_required_free_bytes':need,'observed_free_bytes':need+1,'measured_allocated_bytes':1024,'measured_allocated_plus_next_phase_bytes':1024+need,'declared_total_bytes':2*need}
 files={'capacity.json':json.dumps(capacity).encode(),'unit.log':b'95 passed in 1.0s','parity.log':b'1 passed in 1.0s','owners.log':b'1 passed in 1.0s','torch.log':b'test result: ok. 14 passed; 0 failed; 0 ignored;','native-owners.log':('\n'.join('test '+name+' ... ok' for name in OWNERSHIP_CASES)+'\ntest result: ok. 30 passed; 0 failed; 0 ignored;').encode()}
 gates={}
 for name,artifact in [('transformer_unit','unit.log'),('transformer_parity','parity.log'),('transformer_ownership','owners.log'),('native_torch','torch.log'),('capacity','capacity.json')]:gates[name]={'ran':True,'passed':True,'exit_code':0,'artifact':artifact,'sha256':hashlib.sha256(files[artifact]).hexdigest()}
 gates['native_mlx']={'applicable':False,'reason':'Apple GPU only'}
 return root,files,{'platform':'linux','architecture':'aarch64','profiles':[{'runtime':{'backend':'torch'},'native_module':{'bytes':10}}],'gates':gates}

def test_gate_outputs_and_capacity_are_replayed_not_accepted_as_booleans():
 from tools.rust_migration.transformer_evidence import gate_errors
 root,files,row=gate_fixture();assert gate_errors(files,row,root)==[]

@pytest.mark.parametrize('change',['missing-log','false-unit','skipped','rust-zero','owner-case','reserve','capacity','free','hash'])
def test_resealed_passing_gate_without_its_actual_outputs_is_rejected(change):
 import hashlib
 from tools.rust_migration.transformer_evidence import gate_errors
 root,files,row=gate_fixture()
 if change=='missing-log':files.pop('unit.log')
 elif change=='false-unit':files['unit.log']=b'failed'
 elif change=='skipped':files['unit.log']=b'87 passed, 1 skipped in 1s'
 elif change=='rust-zero':files['torch.log']=b'test result: ok. 0 passed; 0 failed; 0 ignored;'
 elif change=='owner-case':files['native-owners.log']=b'test result: ok. 30 passed; 0 failed; 0 ignored;'
 elif change in ('reserve','capacity','free'):
  value=json.loads(files['capacity.json'])
  if change=='reserve':value['model_plans'][0]['reserve_bytes']=0
  elif change=='capacity':value['declared_total_bytes']=1
  else:value['observed_free_bytes']=1
  files['capacity.json']=json.dumps(value).encode()
 else:row['gates']['native_torch']['sha256']='d'*64
 if change!='hash':
  for gate in row['gates'].values():
   if gate.get('artifact') in files:gate['sha256']=hashlib.sha256(files[gate['artifact']]).hexdigest()
 assert gate_errors(files,row,root)


@pytest.mark.parametrize('field',['declared_core_version','module','libraries'])
def test_forged_actual_runtime_identity_is_rejected_even_when_scores_match(tmp_path,field):
 source,original,files,core,row=profile(tmp_path)
 value=json.loads(files['p/actual.json']);trace=value['rows'][1]['preparation']['runtime']
 if field=='declared_core_version':trace[field]='0.0.0'
 elif field=='module':trace[field]['sha256']='e'*64
 else:trace[field]['lib/libtorch_cpu.dylib']['sha256']='e'*64
 files['p/actual.json']=json.dumps(value).encode()
 assert profile_errors(files,row,original,source,core)


def test_transformer_source_proof_excludes_the_independent_fastembed_executable(tmp_path):
 source=tmp_path/'source'; examples=source/'crates/ken-models/examples';examples.mkdir(parents=True)
 (examples/'fastembed_probe.rs').write_text('fn fastembed_only() {}')
 (examples/'sentence_probe.rs').write_text('fn transformer() {}')
 before=source_identity(source)
 (examples/'fastembed_probe.rs').write_text('fn corrected_fastembed_provenance() {}')
 assert source_identity(source)==before
 (examples/'sentence_probe.rs').write_text('fn changed_transformer() {}')
 assert source_identity(source)!=before
