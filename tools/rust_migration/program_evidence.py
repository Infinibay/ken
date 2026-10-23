"""Authenticate actual native common-model behavior and original provenance."""
from pathlib import Path
from .native_json import load,verify_native_json
from .program_validate import requests,compare_program_observations

def verify_program_capture(out:Path,cases:list[dict],sources:dict|None=None,native_sha256:str|None=None)->list[str]:
 try:
  def require(ok,message):
   if not ok:raise ValueError(message)
  errors=verify_native_json(out,'ken-program-process-');require(not errors,'; '.join(errors))
  build=load(out/'BUILD.json');execution=load(out/'execution.json')
  require(set(build)=={'format','sources','native_sha256'}and build['format']=='ken-program-build/1'and build['sources']==load(out/'SOURCES.json'),'native program source inputs differ')
  if sources is not None:require(build['sources']==sources,'native program source snapshot differs')
  require(build['native_sha256']==execution['native_sha256'],'native program executable differs')
  if native_sha256 is not None:require(build['native_sha256']==native_sha256,'pinned native program executable differs')
  require(load(out/'inputs.json')==requests(cases),'actual native program request differs/contains expectations')
  require(execution['owned_before']=={'native-probe':execution['owned_before']['native-probe']},'unexpected native program resource')
  errors=compare_program_observations(cases,load(out/'stdout.json'));require(not errors,'; '.join(errors));return []
 except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def aggregate_program_matrix(directory:Path,repo:Path,*,snapshot:Path,current:bool=False)->dict:
 """Accept this pure common-model boundary, authenticating both real platforms."""
 import json,re,tarfile,tempfile
 from .integration_validate import _manifest_errors,rust_gate_errors
 from .program_validate import source_identity,program_cases
 from .program_reference import validate_program_reference,program_owner_hashes
 from .native_json import identity
 from .receipts import junit_states
 from .reference import verify_reference
 result=dict(passed=False,M3d_accepted=False,M3_accepted=False,migration_complete=False,errors=[])
 try:
  def require(ok,message):
   if not ok:raise ValueError(message)
  errors=_manifest_errors(directory);require(not errors,'; '.join(errors))
  index=load(directory/'INDEX.json');require(index['format']=='ken-program-matrix/1','wrong program matrix protocol')
  require(index['sources']==source_identity(snapshot/'native-sources'),'native common-model snapshot differs')
  if current:require(index['sources']==source_identity(repo),'current common-model sources differ')
  for name,expected in index['tooling'].items():require(not Path(name).is_absolute()and'..'not in Path(name).parts and identity(snapshot/'validation-sources'/name)==expected,'program validation source differs')
  predecessor=dict(path='docs/validation/rust-migration-2026-10-23/m3-imports-review',sha256='3779ac933aacc766c9372b8e623c4314bd5b65a31bb65735177ba2fa7aa6db6f')
  require(index['predecessor']==predecessor and identity(repo/predecessor['path']/'FILES.json')['sha256']==predecessor['sha256']and not _manifest_errors(repo/predecessor['path']),'closed import predecessor changed')
  require(not verify_reference(repo,repo/'docs/validation/rust-migration-2026-10-18/baseline.json'),'original1066files changed')
  require(set(index['platforms'])=={'macos','linux'},'both actual native platforms required')
  cases=program_cases(snapshot/'native-sources');require(len(cases)==320 and len({c['id']for c in cases})==320 and sum('error'in c['expected']for c in cases)==14,'complete original program corpus required')
  originals=[]
  for system in ('macos','linux'):
   platform=index['platforms'][system];expected=('Darwin','arm64')if system=='macos'else('Linux','aarch64')
   with tempfile.TemporaryDirectory(prefix='ken-program-replay-')as temporary:
    raw=Path(temporary)
    with tarfile.open(directory/(system+'-capture.tar.gz'))as archive:archive.extractall(raw,filter='data')
    reference=load(raw/'original/reference.json');require(not validate_program_reference(reference)and reference['owners']==program_owner_hashes(repo),'original common-model capture differs')
    require(reference['runtime']==dict(system=expected[0],machine=expected[1],python='3.12.9'),'original common-model platform differs')
    require(len(reference['programs'])==88 and len(reference['types'])==204 and len(reference['codecs'])==26 and len(reference['discovered'])==135,'complete original model/type inventories required')
    for name,key in [('stdout.log','stdout_sha256'),('stderr.log','stderr_sha256'),('original-observations.json','observations_sha256')]:require(identity(raw/'original'/name)['sha256']==reference['execution'][key],'actual original process bytes differ')
    observed=load(raw/'original/original-observations.json');require(all(reference[k]==v for k,v in observed.items()),'raw original common-model observations differ')
    discovery={node.split('::',1)[0][:-3].replace('/','.')+'::'+node.split('::',1)[1]for node in reference['discovered']};states=junit_states(raw/'original/original-tests.xml')
    require(set(states)==discovery and set(states.values())=={'passed'},'actual original model test execution differs')
    originals.append(reference)
    errors=verify_program_capture(raw/'native',cases,index['sources'],platform['native_sha256']);require(not errors,'; '.join(errors))
    execution=load(raw/'native/execution.json');require((execution['system'],execution['machine'])==(system,expected[1]),'native common-model platform differs')
    gates=raw/'gates';listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
    require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==7,'complete7native root cases required')
    discovered={path[:-3].replace('/','.')+'::'+name for path,name in re.findall(r'^(tests/rust_migration/test_program_(?:reference|validate|evidence)\.py)::(.+)$',(gates/'python-list.log').read_text(),re.M)};states=junit_states(gates/'python.xml')
    require(len(discovered)==28 and set(states)==discovered and set(states.values())=={'passed'},'complete28affected tooling cases required')
    clippy=(gates/'clippy.log').read_text();require('Finished `dev` profile'in clippy and'error:'not in clippy and'warning:'not in clippy,'clippy missing/failed')
    require((gates/'fmt.log').read_bytes()==b'','format missing/failed')
  fixtures=snapshot/'native-sources/crates/ken-program/tests/fixtures';program_fixture=load(fixtures/'program-reference.json');type_fixture=load(fixtures/'type-reference.json');vocabulary=load(fixtures/'vocabulary.json')
  union={}
  for original in originals:
   for row in original['programs']:
    if row['id']in union:require(union[row['id']]==row,'same original program input changed result')
    else:union[row['id']]=row
  require(len(union)==90 and program_fixture['programs']==list(union.values()),'complete actual original program union differs')
  require(program_fixture['codecs']==originals[0]['codecs']==originals[1]['codecs']and type_fixture['types']==originals[0]['types']==originals[1]['types'],'original codec/type cases differ')
  require(vocabulary['vocabulary']==originals[0]['vocabulary']==originals[1]['vocabulary'],'original grammar/Unicode vocabulary differs')
  for fixture in (program_fixture,type_fixture,vocabulary):require(fixture['owners']==program_owner_hashes(repo)and fixture['original_corpus_sha256']==[v['corpus_sha256']for v in originals],'native original fixture provenance differs')
  compiled=load(snapshot/'native-sources/crates/ken-program/src/kinds.json');require(compiled=={k:vocabulary['vocabulary'][k]for k in ('native','operations')},'native kind mapping differs from actual original')
  unicode=load(snapshot/'native-sources/crates/ken-program/src/unicode15.json');require(unicode['word_ranges']==vocabulary['vocabulary']['word_ranges']and unicode['unicode_version']==vocabulary['vocabulary']['unicode_version']=='15.0.0','native annotation word properties differ')
  result.update(passed=True,M3d_accepted=True,per_platform=dict(Rust=7,Python=28,program_inputs=90,type_inputs=204,codecs=26,lookups=1240,original_tests=135))
 except(OSError,ValueError,KeyError,TypeError,IndexError,tarfile.TarError)as error:result['errors'].append(str(error))
 return result
