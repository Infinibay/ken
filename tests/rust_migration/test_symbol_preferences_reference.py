from pathlib import Path
import gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]
def original():
    from tools.rust_migration.symbol_preferences_reference import FIXTURE
    return json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
def test_new_preferences_original_covers_fixed_query_policy_and_real_catalog():
    from tools.rust_migration.symbol_preferences_reference import cases,validate_reference
    value=original();assert not validate_reference(value)
    assert len(value['cases'])==len(cases()) and value['catalogs'][0]['result']
@pytest.mark.parametrize('change',['input','observer','suite','runtime','result','catalog','fingerprint'])
def test_changed_preference_original_rejects(change):
    from tools.rust_migration.symbol_preferences_reference import validate_reference
    value=original()
    if change=='input':value['cases'][0]['input']={}
    elif change=='observer':value['script_sha256']='a'*64
    elif change=='suite':value['test_states'][0]['outcome']='skipped'
    elif change=='runtime':value['runtime']['machine']='aarch64'
    elif change=='result':value['cases'][0]['result']={}
    elif change=='catalog':value['catalogs'][0]['input']['files']={}
    else:value['reference_fingerprint']='a'*64
    assert validate_reference(value)
def test_existing_preference_destination_never_reads_reference_or_recaptures(tmp_path,monkeypatch):
    from tools.rust_migration import symbol_preferences_reference as module
    from tools.rust_migration.reference import Reference
    unused=tmp_path/'missing';reference=Reference(unused,unused/'manifest','unused',unused/'python')
    monkeypatch.setattr(module,'verify_reference',lambda *a:pytest.fail('reference read'))
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:pytest.fail('original recaptured'))
    with pytest.raises(FileExistsError):module.capture(reference,tmp_path)
