"""New package assembly uses existing authenticated resource staging, not models."""
import hashlib,json,os,shutil
from pathlib import Path
import pytest
from tools import native_package
from tools.rust_migration import public_search_resources

def identity(path):
 return {'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

def inputs(tmp_path,monkeypatch):
 repo=tmp_path/'repo';repo.mkdir();(repo/'LICENSE').write_text('fixture product license')
 static=repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz';static.parent.mkdir(parents=True);static.write_bytes(b'fixture static data')
 declarations=repo/'crates/ken-models/resources';declarations.mkdir(parents=True);(declarations/'legacy-compatibility.json').write_text(json.dumps({'static_table':{'model_id':'ken/static-qwen3-r512-v2',**identity(static)}}))
 source=tmp_path/'source';source.mkdir();files={};variables={}
 for name,variable in public_search_resources.MODELS:
  payload=source/name;payload.write_bytes(name.encode());revision='a'*40;destination=f'inputs/models/{name}/{revision}'
  files[destination+'/data']=dict(source=str(payload),artifact=identity(payload));variables[variable]=destination
  (declarations/(name+'.json')).write_text(json.dumps({'model_id':'fixture/'+name,'revision':revision,'license':'fixture','artifacts':{'data':identity(payload)}}))
 for destination in ['inputs/onnx/core.so','inputs/ct2/module.so']:
  files[destination]=dict(source='/bin/true',artifact=identity(Path('/bin/true')))
 grammar=source/'grammar.json';grammar.write_text('{"libraries":[]}');files['inputs/grammars/manifest.json']=dict(source=str(grammar),artifact=identity(grammar));variables['KEN_GRAMMAR_MANIFEST']='inputs/grammars/manifest.json';variables['KEN_PUBLIC_RANKS']='inputs/ranking';variables['KEN_ORT_LIBRARY']='inputs/onnx/core.so';variables['KEN_CT2_PREPARATION']='inputs/translation-runtime.json'
 # The resource-selection seam is controlled; the real shared stage verifies and copies every file.
 plan=dict(format='ken-public-search-inputs/1',files=files,environment=variables,translation={'registration':{'format':'ken-native-translation/1','runtimes':[{'os':'linux','arch':'x86_64','core_version':'4.8.2','abi':1,'module':identity(Path('/bin/true')),'libraries':{}}]},'module_path':'inputs/ct2/module.so','core_root':'inputs/ct2'})
 monkeypatch.setattr(public_search_resources,'plan',lambda *_:plan)
 license_file=source/'LICENSE';license_file.write_text('fixture license payload')
 license_index=source/'licenses.json';license_index.write_text(json.dumps({'format':'ken-native-package-licenses/1','files':{'licenses/fixture.txt':{'source':str(license_file),**identity(license_file)}},'components':['ken','rust','grammars','ranking','static','potion','context','ettin','translation','onnx','ct2','dense','elf','git']}))
 closure=source/'elf.json';closure.write_text(json.dumps({'format':'ken-native-elf-closure/1','files':{},'system_libraries':['libc.so.6','ld-linux-x86-64.so.2'],'baseline':'fixture-host'}))
 environment={'KEN_PACKAGE_LICENSES':str(license_index),'KEN_PACKAGE_ELF_CLOSURE':str(closure)}
 binaries={name:Path('/bin/true') for name in ['launcher','cli','check_worker','git']}
 provenance={'source':{'commit':'a'*40,'dirty':False},'build':{'rustc':'fixture','profile':'contract-fixture'},'runtime':{'baseline':'fixture-host'},'qualification':{'accepted':False,'scope':'contract-fixture'}}
 provenance['legacy_runtime']=json.loads((Path(__file__).parents[1]/'crates/ken-models/tests/fixtures/profile-identity/linux.json').read_text())['legacy_runtime']
 return repo,environment,binaries,provenance

def test_bundle_closes_inventory_portable_paths_modes_and_runtime_license_inputs(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);destination=tmp_path/'bundle'
 result=native_package.build_bundle(repo,environment,binaries,destination,provenance)
 raw=(destination/'FILES.json').read_bytes();manifest=json.loads(raw)
 assert result['manifest_sha256']==hashlib.sha256(raw).hexdigest()
 assert manifest['format']=='ken-native-package/1'
 assert manifest['target']=={'os':'linux','arch':'x86_64','device':'cpu'}
 assert manifest['entrypoints']=={'launcher':'ken','cli':'ken-rs','check_worker':'ken-check-worker','git':'git'}
 assert 'inputs/static/ken__static-qwen3-r512-v2.npz' in manifest['files']
 assert 'licenses/fixture.txt' in manifest['files']
 assert manifest['provenance']['qualification']['accepted'] is False
 declared=set(manifest['files'])|{'FILES.json'};actual={str(path.relative_to(destination))for path in destination.rglob('*')if path.is_file()}
 assert declared==actual
 for name,row in manifest['files'].items():
  path=destination/name
  assert identity(path)=={'bytes':row['bytes'],'sha256':row['sha256']}
  assert path.stat().st_mode&0o777==row['mode']
 resources=json.loads((destination/manifest['resources']).read_text())
 assert resources['private_parent']=='../../../var/private'
 assert resources['cache_parent']=='../../../var/cache'
 assert not Path(resources['bundled_npz']).is_absolute()
 assert str(tmp_path) not in (destination/'inputs/translation-runtime.json').read_text()
 assert native_package.authenticate_bundle(destination)['manifest_sha256']==result['manifest_sha256']

def test_changed_authenticated_source_never_publishes_a_partial_bundle(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);original=public_search_resources.plan(repo,environment);first=next(iter(original['files'].values()));Path(first['source']).write_bytes(b'tampered')
 destination=tmp_path/'bundle'
 with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,destination,provenance)
 assert not destination.exists()

def test_builder_rejects_incomplete_elf_licenses_foreign_destinations_and_existing_output(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch)
 for key in ['KEN_PACKAGE_ELF_CLOSURE','KEN_PACKAGE_LICENSES']:
  incomplete=dict(environment);incomplete.pop(key)
  with pytest.raises((ValueError,KeyError)):native_package.build_bundle(repo,incomplete,binaries,tmp_path/key,provenance)
 destination=tmp_path/'existing';destination.mkdir();(destination/'foreign').write_text('keep')
 with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,destination,provenance)
 assert (destination/'foreign').read_text()=='keep'
 plan=public_search_resources.plan(repo,environment);row=next(iter(plan['files'].values()));plan['files']['../escape']=row
 with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,tmp_path/'escape',provenance)
 assert not (tmp_path/'escape').exists()

def test_authentication_rejects_tampered_files_and_symlink_or_mode_substitution(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);root=tmp_path/'bundle';native_package.build_bundle(repo,environment,binaries,root,provenance)
 original=(root/'ken-rs').read_bytes();os.chmod(root/'ken-rs',0o755);(root/'ken-rs').write_bytes(b'tampered')
 with pytest.raises(ValueError):native_package.authenticate_bundle(root)
 (root/'ken-rs').write_bytes(original);os.chmod(root/'ken-rs',0o555);(root/'foreign').symlink_to('/etc/passwd')
 with pytest.raises(ValueError):native_package.authenticate_bundle(root)

def test_optional_native_transformer_declaration_and_sources_remain_closed_and_portable(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch)
 declaration={'registration':{'format':'ken-native-transformer/1','backend':'torch','runtimes':[{'os':'linux','arch':'x86_64','core_version':'2.9.0','module':identity(Path('/bin/true')),'libraries':{'lib/core.so':identity(Path('/bin/true'))}}]},'module_path':'native/torch/backend.so','core_root':'native/torch'}
 extra=tmp_path/'extra.json';extra.write_text(json.dumps({'format':'ken-package-transformers/1','torch':declaration,'files':{'native/torch/backend.so':{'source':'/bin/true',**identity(Path('/bin/true'))},'native/torch/lib/core.so':{'source':'/bin/true',**identity(Path('/bin/true'))}},'sources':{'fixture/encoder':'inputs/models/potion-code-16M-v2/'+'a'*40}}))
 environment['KEN_PACKAGE_TRANSFORMERS']=str(extra)
 licenses=Path(environment['KEN_PACKAGE_LICENSES']);index=json.loads(licenses.read_text());index['components'].append('torch');licenses.write_text(json.dumps(index))
 root=tmp_path/'bundle';native_package.build_bundle(repo,environment,binaries,root,provenance)
 resource=json.loads((root/'resources/search.json').read_text());assert resource['torch']=={**declaration,'module_path':'../native/torch/backend.so','core_root':'../native/torch'}
 assert resource['sources']['fixture/encoder'].startswith('../inputs/')
 assert native_package.authenticate_bundle(root)['provenance']['qualification']['accepted'] is False

def with_catalogue(root,declaration,payload=b'contract catalogue fixture'):
 catalogue=root/'resources/catalogue.json';catalogue.write_bytes(payload);catalogue.chmod(0o444)
 resources=root/'resources/search.json';raw=json.loads(resources.read_text());raw['catalogue_extensions']=declaration
 resources.chmod(0o644);resources.write_text(json.dumps(raw));resources.chmod(0o444)
 path=root/'FILES.json';manifest=json.loads(path.read_text())
 for source in [catalogue,resources]:manifest['files'][source.relative_to(root).as_posix()]={**identity(source),'mode':0o444}
 path.chmod(0o644);path.write_text(json.dumps(manifest));path.chmod(0o444)

def test_owned_catalogue_binding_is_valid_without_loading_any_model(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);root=tmp_path/'bundle';native_package.build_bundle(repo,environment,binaries,root,provenance)
 payload=b'contract catalogue fixture';with_catalogue(root,{'path':'catalogue.json','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
 assert native_package.authenticate_bundle(root)['provenance']['qualification']['accepted'] is False

@pytest.mark.parametrize('kind',['absolute','traversal','undeclared','bytes','sha256'])
def test_catalogue_binding_rejects_external_or_inventory_inconsistent_data(tmp_path,monkeypatch,kind):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);root=tmp_path/'bundle';native_package.build_bundle(repo,environment,binaries,root,provenance)
 payload=b'contract catalogue fixture';external=tmp_path/'catalogue.json';external.write_bytes(payload)
 declaration={'path':'catalogue.json','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
 if kind=='absolute':declaration['path']=str(external)
 elif kind=='traversal':declaration['path']='../../catalogue.json'
 elif kind=='undeclared':declaration['path']='missing.json'
 elif kind=='bytes':declaration['bytes']+=1
 else:declaration['sha256']='0'*64
 with_catalogue(root,declaration)
 with pytest.raises(ValueError):native_package.authenticate_bundle(root)

def actual_native_build(tmp_path):
 from test_native_release import repository
 from tools.native_release import build_release
 import subprocess
 repo=repository(tmp_path/'native-repo')
 subprocess.run([shutil.which('git'),'-C',str(repo),'-c','user.name=Native package fixture','-c','user.email=native-package-fixture@example.invalid','commit','-qm','isolated native package fixture'],check=True)
 directory=tmp_path/'native-build';receipt=build_release(repo,directory)
 return directory,receipt,{role:directory/row['path']for role,row in receipt['artifacts'].items()}

def test_supplied_build_boolean_cannot_establish_source_binding(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);provenance['build']['source_binary_binding_verified']=True
 result=native_package.build_bundle(repo,environment,binaries,tmp_path/'bundle',provenance)
 assert result['provenance']['build']['source_binary_binding_verified'] is False

def test_missing_native_build_receipt_rejects_before_bundle_publication(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);environment['KEN_NATIVE_BUILD']=str(tmp_path/'missing-build')
 destination=tmp_path/'bundle'
 with pytest.raises((ValueError,FileNotFoundError)):native_package.build_bundle(repo,environment,binaries,destination,provenance)
 assert not destination.exists()

@pytest.mark.parametrize('kind',['valid','substituted_cli','tampered_receipt'])
def test_actual_native_build_binding_is_rechecked_before_candidate_publication(tmp_path,monkeypatch,kind):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);directory,receipt,native_binaries=actual_native_build(tmp_path)
 binaries.update(native_binaries);environment['KEN_NATIVE_BUILD']=str(directory);destination=tmp_path/'bundle'
 closure=Path(environment['KEN_PACKAGE_ELF_CLOSURE']);declared=json.loads(closure.read_text());declared['system_libraries']+=['libgcc_s.so.1','libm.so.6'];closure.write_text(json.dumps(declared))
 if kind=='substituted_cli':binaries['cli']=Path('/bin/true')
 if kind=='tampered_receipt':
  path=directory/'BUILD.json';value=json.loads(path.read_text());value['build']['command']=['/bin/true'];path.write_text(json.dumps(value))
 if kind!='valid':
  with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,destination,provenance)
  assert not destination.exists();return
 result=native_package.build_bundle(repo,environment,binaries,destination,provenance);captured=result['provenance']
 assert captured['source']['sha256']==receipt['source']['sha256']
 assert captured['source']['commit']==receipt['source']['commit']
 assert captured['source']['dirty']==receipt['source']['dirty']
 assert captured['source']['commit']!=provenance['source']['commit']
 assert captured['build']['native_build']['receipt']==identity(directory/'BUILD.json')
 assert captured['build']['source_binary_binding_verified'] is True
 assert captured['qualification']['accepted'] is False
 assert native_package.authenticate_bundle(destination)['provenance']==captured

def native_dependency(tmp_path,rpath=None,old_dtags=False):
 import subprocess
 directory=tmp_path/'native-dependency';directory.mkdir();(directory/'library.cc').write_text('extern "C" int fixture(){return 42;}\n');(directory/'main.cc').write_text('extern "C" int fixture();int main(){return fixture()==42?0:1;}\n')
 compiler=shutil.which('cc');assert compiler,'explicit build-host C++ capable cc required'
 library=directory/'libfixture.so';subprocess.run([compiler,'-x','c++','-fPIC','-shared',str(directory/'library.cc'),'-Wl,-soname,libfixture.so','-o',str(library)],check=True,capture_output=True)
 binary=directory/'backend';command=[compiler,'-x','c++',str(directory/'main.cc'),'-L'+str(directory),'-lfixture','-o',str(binary)]
 if rpath is not None:
  if old_dtags:command+=['-Wl,--disable-new-dtags']
  command+=['-Wl,-rpath,'+str(rpath)]
 subprocess.run(command,check=True,capture_output=True)
 return binary,library

def add_dependency_input(repo,environment,binary,library,destination):
 plan=public_search_resources.plan(repo,environment);plan['files'][destination]={'source':str(library),'artifact':identity(library)}

def test_elf_dependency_in_unsearched_staged_directory_cannot_satisfy_loader_closure(tmp_path,monkeypatch):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);binary,library=native_dependency(tmp_path)
 binaries['cli']=binary;add_dependency_input(repo,environment,binary,library,'unused/libfixture.so')
 destination=tmp_path/'bundle'
 with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,destination,provenance)
 assert not destination.exists()

@pytest.mark.parametrize('old_dtags',[False,True])
def test_elf_external_developer_rpath_is_rejected_even_when_dependency_is_bundled(tmp_path,monkeypatch,old_dtags):
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);binary,library=native_dependency(tmp_path,tmp_path/'developer-only',old_dtags)
 binaries['cli']=binary;add_dependency_input(repo,environment,binary,library,'lib/libfixture.so');destination=tmp_path/'bundle'
 with pytest.raises(ValueError):native_package.build_bundle(repo,environment,binaries,destination,provenance)
 assert not destination.exists()

def test_elf_owned_origin_path_relocates_to_real_available_dependency_without_host_path(tmp_path,monkeypatch):
 import subprocess
 repo,environment,binaries,provenance=inputs(tmp_path,monkeypatch);binary,library=native_dependency(tmp_path,'$ORIGIN/lib')
 binaries['cli']=binary;add_dependency_input(repo,environment,binary,library,'lib/libfixture.so');destination=tmp_path/'bundle'
 result=native_package.build_bundle(repo,environment,binaries,destination,provenance)
 executed=subprocess.run([destination/'ken-rs'],env={'PATH':'','LD_LIBRARY_PATH':str(destination/'lib')},cwd=tmp_path,check=False)
 assert executed.returncode==0
 assert result['provenance']['qualification']['accepted'] is False
