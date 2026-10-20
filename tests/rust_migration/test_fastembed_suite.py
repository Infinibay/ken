"""Prepare network data before the bounded native process-test execution."""
from contextlib import contextmanager
import hashlib,io,json
from pathlib import Path
import pytest
from tools.rust_migration import fastembed_sources as sources,model_validate as validator
from tools.rust_migration.fastembed_ownership import MODELS
from tools.rust_migration.preparation import PreparedNativeFastEmbed


def fixture_catalogue():
    return {'models':[{'name':name,'assets':{'model_id':name,'revision':'b'*40,
        'artifacts':{'weights.onnx':{'bytes':7,'sha256':hashlib.sha256(b'weights').hexdigest()}}}}
        for name in MODELS]}


def test_suite_holds_all_five_sources_then_removes_only_its_files(tmp_path,monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda url,timeout:io.BytesIO(b'weights'))
    registry=tmp_path/'registry.json';registry.write_text(json.dumps(fixture_catalogue()))
    cache=tmp_path/'cache';cache.mkdir();keep=cache/'keep';keep.write_bytes(b'original')
    requested=PreparedNativeFastEmbed(tmp_path/'probe',cache,registry,acquire=True)
    with sources.suite_source_lease(requested,environ={})as ready:
        assert not ready.acquire
        assert len(list(ready.sources.iterdir()))==5
        for name in MODELS:
            assert (ready.sources/name.replace('/','--')/('b'*40)/'weights.onnx').read_bytes()==b'weights'
    assert list(cache.iterdir())==[keep] and keep.read_bytes()==b'original'


def test_suite_preparation_failure_removes_every_partially_acquired_model(tmp_path,monkeypatch):
    import urllib.request
    attempts=[]
    def download(url,timeout):
        attempts.append(url)
        return io.BytesIO(b'wrong'if len(attempts)==3 else b'weights')
    monkeypatch.setattr(urllib.request,'urlopen',download)
    registry=tmp_path/'registry.json';registry.write_text(json.dumps(fixture_catalogue()))
    cache=tmp_path/'cache';cache.mkdir()
    requested=PreparedNativeFastEmbed(tmp_path/'probe',cache,registry,acquire=True)
    with pytest.raises(ValueError,match='artifact'):
        with sources.suite_source_lease(requested,environ={}):pytest.fail('incomplete inputs exposed')
    assert list(cache.iterdir())==[]


def test_download_preparation_is_outside_suite_deadline_and_child_is_offline(tmp_path,monkeypatch):
    requested=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path/'downloads',tmp_path/'registry',acquire=True)
    ready=PreparedNativeFastEmbed(requested.probe,tmp_path/'ready',requested.registry)
    clock=[1000.0];observed={}
    @contextmanager
    def prepare(prepared,*,environ):
        assert prepared is requested
        clock[0]+=900
        yield ready
        observed['released']=True
    monkeypatch.setattr(sources,'suite_source_lease',prepare)
    monkeypatch.setattr(validator.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(validator.time,'monotonic_ns',lambda:int(clock[0]*1e9))
    environment=requested.environment()
    def command(repo,env,out,name,argv,timeout_s=600):
        assert name=='parity-tests'and timeout_s==600
        assert env['KEN_FASTEMBED_SOURCES']==str(ready.sources)
        assert 'KEN_FASTEMBED_ACQUIRE'not in env
        assert float(env['KEN_FASTEMBED_VALIDATION_DEADLINE'])==pytest.approx(2495)
        observed['ran']=True
        return {'ran':True,'passed':True,'exit':0}
    monkeypatch.setattr(validator,'_command',command)
    result=validator.run_parity_suite(tmp_path,environment,tmp_path,['python','-m'],requested)
    assert result['passed']and result['preparation']['duration_ns']==900_000_000_000
    assert observed=={'ran':True,'released':True}
    assert environment==requested.environment()
