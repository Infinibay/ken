from pathlib import Path
import gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]
def original():
    from tools.rust_migration.syntax_witnesses_reference import FIXTURE
    return json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
def test_first_syntax_witnesses_match_fixed_sources_and_actual_owner_cache():
    from tools.rust_migration.syntax_witnesses_reference import cases,validate_reference
    value=original();assert len(value['cases'])==len(cases())and not validate_reference(value)
    assert any(r['cold']for c in value['cases']for r in c['result'])
@pytest.mark.parametrize('change',['observer','inputs','source','result','suite','runtime','fingerprint'])
def test_changed_syntax_witness_reference_rejects(change):
    from tools.rust_migration.syntax_witnesses_reference import validate_reference
    value=original()
    if change=='observer':value['script_sha256']='a'*64
    elif change=='inputs':value['inputs_sha256']='a'*64
    elif change=='source':value['cases'][0]['input']['files']={}
    elif change=='result':value['cases'][0]['result']=[]
    elif change=='suite':value['test_states'][0]['outcome']='skipped'
    elif change=='runtime':value['runtime']['machine']='aarch64'
    else:value['reference_fingerprint']='a'*64
    assert validate_reference(value)
def test_existing_syntax_capture_never_reads_reference_or_recaptures(tmp_path,monkeypatch):
    from tools.rust_migration import syntax_witnesses_reference as module
    from tools.rust_migration.reference import Reference
    missing=tmp_path/'missing';ref=Reference(missing,missing/'manifest','unused',missing/'python')
    monkeypatch.setattr(module,'verify_reference',lambda *a:pytest.fail('reference read'))
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:pytest.fail('recaptured'))
    with pytest.raises(FileExistsError):module.capture(ref,tmp_path)
