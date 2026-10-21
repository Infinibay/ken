"""One owned model lease at a time, with measured free-space reservation."""
from pathlib import Path
import hashlib,json
import pytest
from tools.rust_migration.preparation import PreparedNativeTransformer
from tools.rust_migration.transformer_sources import capacity_plan,source_lease

def prepared(root,acquire=False):
 return PreparedNativeTransformer(*(root/p for p in ('probe','sources','catalog','module','core','runtimes')),acquire=acquire)

def definition():
 return {'name':'fixtures/model','assets':{'model_id':'fixtures/model','revision':'a'*40,'license':'MIT','artifacts':{'model.safetensors':{'bytes':4,'sha256':hashlib.sha256(b'data').hexdigest()}}}}

def test_explicit_typed_paths_and_acquisition_policy(tmp_path):
 assert prepared(tmp_path).environment()['KEN_TRANSFORMER_SOURCES']==str(tmp_path/'sources')
 with pytest.raises(ValueError):prepared(Path('.')).environment()
 with pytest.raises(ValueError):prepared(tmp_path,1).environment()

def test_capacity_accounts_private_model_and_native_core_and_three_gib_reserve():
 result=capacity_plan(definition(),{'libraries':{'lib/core':{'bytes':100}}},module_bytes=20,acquire=True)
 assert result['model_source_bytes']==4 and result['private_bytes']==124
 assert result['required_free_bytes']==4+124+3*1024**3

def test_borrowed_source_verified_and_untouched_even_when_consumer_fails(tmp_path):
 ready=prepared(tmp_path);model=definition();snapshot=ready.sources/'fixtures--model'/('a'*40);snapshot.mkdir(parents=True);(snapshot/'model.safetensors').write_bytes(b'data')
 with pytest.raises(RuntimeError):
  with source_lease(ready,model,{'libraries':{}},module_bytes=1) as lease:
   assert lease.sources==ready.sources;raise RuntimeError('consumer')
 assert (snapshot/'model.safetensors').read_bytes()==b'data'
 (snapshot/'model.safetensors').write_bytes(b'bad!')
 with pytest.raises(ValueError,match='artifact'): 
  with source_lease(ready,model,{'libraries':{}},module_bytes=1):pass

def test_owned_acquisition_releases_only_its_temporary_subtree(tmp_path,monkeypatch):
 from tools.rust_migration import transformer_sources as module
 ready=prepared(tmp_path,True);ready.sources.mkdir();sentinel=ready.sources/'existing';sentinel.write_text('keep')
 def download(assets,snapshot):
  (snapshot/'model.safetensors').write_bytes(b'data')
 monkeypatch.setattr(module,'_download',download)
 with source_lease(ready,definition(),{'libraries':{}},module_bytes=1) as lease:
  assert lease.acquire is False and lease.sources!=ready.sources
  owned=lease.sources;assert owned.is_dir()
 assert not owned.exists() and sentinel.read_text()=='keep' and list(ready.sources.iterdir())==[sentinel]


def test_native_test_preparation_is_complete_typed_and_survives_filtered_validator_environment(tmp_path):
 from tools.rust_migration.preparation import PreparedTransformerTests,transformer_test_environment
 paths=[tmp_path/p for p in ('metadata','torch','module','record')]
 prepared=PreparedTransformerTests(*paths)
 values=prepared.environment();assert set(values)=={'KEN_TRANSFORMER_SOURCE_ROOT','KEN_TORCH_CORE','KEN_TORCH_MODULE','KEN_TORCH_PREPARATION'}
 assert transformer_test_environment(environ=values)==values
 assert transformer_test_environment(environ={})=={}
 for key in values:
  with pytest.raises(ValueError):transformer_test_environment(environ={key:values[key]})
 with pytest.raises(ValueError):PreparedTransformerTests(*paths,mlx_core=tmp_path/'mlx').environment()


def test_metadata_preparation_never_downloads_or_copies_weights(tmp_path,monkeypatch):
 from tools.rust_migration import transformer_prepare as module
 model=definition();model['assets']['artifacts']['tokenizer.json']={'bytes':2,'sha256':hashlib.sha256(b'{}').hexdigest()}
 registry=tmp_path/'catalog.json';registry.write_text(json.dumps({'models':[model]}));source=tmp_path/'borrowed'/'fixtures--model'/('a'*40);source.mkdir(parents=True);(source/'model.safetensors').write_bytes(b'data');(source/'tokenizer.json').write_bytes(b'{}')
 destination=tmp_path/'metadata';module.prepare_tokenizer_sources(registry,destination,borrowed_sources=tmp_path/'borrowed')
 assert (destination/'fixtures--model'/('a'*40)/'tokenizer.json').read_bytes()==b'{}'
 assert not list(destination.rglob('*.safetensors')) and (source/'model.safetensors').read_bytes()==b'data'


def test_prior_validator_restores_only_explicit_native_test_inputs_after_reference_filter(tmp_path,monkeypatch):
 import sys
 from tools.rust_migration import model_validate as module
 from tools.rust_migration.reference import Reference
 expected={key:str(tmp_path/name) for key,name in [('KEN_TRANSFORMER_SOURCE_ROOT','metadata'),('KEN_TORCH_CORE','core'),('KEN_TORCH_MODULE','module'),('KEN_TORCH_PREPARATION','record')]}
 for key,value in expected.items():monkeypatch.setenv(key,value)
 for key in ('KEN_MLX_CORE','KEN_MLX_MODULE'):monkeypatch.delenv(key,raising=False)
 seen={}
 class Reached(BaseException):pass
 def command(repo,env,*args):seen.update(env);raise Reached()
 monkeypatch.setattr(module,'_verify',lambda *a:{'passed':True});monkeypatch.setattr(module,'_model_fingerprints',lambda *a:{});monkeypatch.setattr(module,'_rustc_version',lambda *a:'rustc 1.95.0 test');monkeypatch.setattr(module,'_command',command)
 reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
 with pytest.raises(Reached):module.validate_models(tmp_path,reference,tmp_path/'probe',tmp_path/'potion',tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest')
 assert {key:seen.get(key) for key in expected}==expected
