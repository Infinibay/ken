"""Owned acquisition leases bound disk use without modifying borrowed sources."""
import hashlib,io,json,shutil
from pathlib import Path
import pytest
from tools.rust_migration.preparation import PreparedNativeFastEmbed,fastembed_environment
from tools.rust_migration.fastembed_sources import source_lease,capacity_plan,check_capacity


def model(data=b'weights'):
    return {'name':'owner/model','assets':{'model_id':'owner/model','revision':'a'*40,
        'artifacts':{'weights.onnx':{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}}


def test_owned_sources_are_verified_then_removed_even_after_failure(tmp_path,monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda url,timeout:io.BytesIO(b'weights'))
    sources=tmp_path/'sources';sources.mkdir();unrelated=sources/'keep';unrelated.write_bytes(b'original')
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',sources,tmp_path/'registry',acquire=True)
    with pytest.raises(RuntimeError,match='consumer failed'):
        with source_lease(prepared,model(),copies=3)as leased:
            snapshot=leased.sources/'owner--model'/('a'*40)
            assert (snapshot/'weights.onnx').read_bytes()==b'weights'
            assert not leased.acquire and leased.sources!=sources
            assert unrelated.read_bytes()==b'original'
            raise RuntimeError('consumer failed')
    assert list(sources.iterdir())==[unrelated]


@pytest.mark.parametrize('data',[b'corrupt',b'short',b'weights-too-large'])
def test_partial_or_changed_download_never_publishes_ready_sources(tmp_path,monkeypatch,data):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda url,timeout:io.BytesIO(data))
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path,tmp_path/'registry',acquire=True)
    with pytest.raises(ValueError,match='artifact'):
        with source_lease(prepared,model(),copies=2):pytest.fail('corrupt source was exposed')
    assert list(tmp_path.iterdir())==[]


def test_borrowed_sources_are_never_downloaded_or_deleted(tmp_path,monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('borrowed source downloaded'))
    keep=tmp_path/'weights';keep.write_bytes(b'original')
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path,tmp_path/'registry')
    with source_lease(prepared,model(),copies=3)as leased:assert leased is prepared
    assert keep.read_bytes()==b'original'


def test_insufficient_capacity_fails_before_download_and_cleans_nothing(tmp_path,monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('download started without capacity'))
    monkeypatch.setattr(shutil,'disk_usage',lambda p:shutil._ntuple_diskusage(100,99,1))
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path,tmp_path/'registry',acquire=True)
    with pytest.raises(OSError,match='capacity'):
        with source_lease(prepared,model(),copies=3):pytest.fail('insufficient capacity exposed')
    assert list(tmp_path.iterdir())==[]


def test_complete_catalogue_schedule_fits_declared_source_budget():
    from tools.rust_migration.fastembed_ownership import MODELS
    catalogue=json.loads(Path('crates/ken-models/resources/fastembed-catalog.json').read_bytes())
    plan=capacity_plan(catalogue)
    assert len(plan['parity'])==30 and len(plan['ownership'])==5
    assert [r['model']for r in plan['ownership']]==MODELS
    assert all(r['copies']==2 for r in plan['parity'])
    assert all(r['copies']==3 for r in plan['ownership'])
    assert plan['peak_bytes']<8*1024**3
    assert plan['peak_bytes']+plan['build_headroom_bytes']<14_000_000_000
    check_capacity(Path('.'),plan['peak_bytes'])


def test_acquisition_is_explicit_and_forwarded_without_changing_default(tmp_path,monkeypatch):
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path/'sources',tmp_path/'registry',acquire=True)
    values=prepared.environment();assert values['KEN_FASTEMBED_ACQUIRE']=='1'
    for key,value in values.items():monkeypatch.setenv(key,value)
    assert fastembed_environment()==values
    monkeypatch.setenv('KEN_FASTEMBED_ACQUIRE','false')
    with pytest.raises(ValueError,match='acquisition'):fastembed_environment()


def test_every_catalogue_lease_and_ownership_family_releases_its_budget(tmp_path,monkeypatch):
    """All declared owners take turns in a shared constrained acquisition area."""
    import urllib.request
    from tools.rust_migration.fastembed_ownership import MODELS
    catalogue=json.loads(Path('crates/ken-models/resources/fastembed-catalog.json').read_bytes())
    downloaded=[]
    def download(url,timeout):downloaded.append(url);return io.BytesIO(b'weights')
    monkeypatch.setattr(urllib.request,'urlopen',download)
    # Keep the full catalogue identities/order, using tiny authenticated data to
    # exercise actual create/write/verify/remove rather than allocating 19 GB.
    for definition in catalogue['models']:
        original=definition['assets'];definition['assets']=model()['assets']|{
            'model_id':original['model_id'],'revision':original['revision']}
    budget=512*1024**2+21
    monkeypatch.setattr(shutil,'disk_usage',lambda p:shutil._ntuple_diskusage(budget,0,budget))
    prepared=PreparedNativeFastEmbed(tmp_path/'probe',tmp_path,tmp_path/'registry',acquire=True)
    seen=[]
    for definition,copies in ([(d,2)for d in catalogue['models']]+[
            (next(d for d in catalogue['models']if d['name']==name),3)for name in MODELS]):
        with source_lease(prepared,definition,copies=copies)as leased:
            assert len(list(tmp_path.iterdir()))==1
            assert sum(p.stat().st_size for p in leased.sources.rglob('*')if p.is_file())==7
            seen.append((definition['name'],copies))
        assert list(tmp_path.iterdir())==[]
    assert len(downloaded)==35 and len(seen)==35
    assert [name for name,copies in seen if copies==3]==MODELS
