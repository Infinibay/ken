"""New symbol-view observations are disjoint, fixed and never auto-recaptured."""
from dataclasses import replace
from pathlib import Path
import gzip,json
import pytest

ROOT=Path(__file__).resolve().parents[2]
def original():
    from tools.rust_migration.symbol_views_reference import FIXTURE
    return json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))

def test_symbol_view_original_covers_fixed_cases_real_frames_and_new_fusion_witness():
    from tools.rust_migration.symbol_views_reference import cases,frames,validate_reference
    value=original();assert not validate_reference(value)
    assert len(value['cases'])==len(cases())and len(value['frames'])==len(frames())==5
    assert value['fusion_grouping_extension']['result']==[1,0]

@pytest.mark.parametrize('change',['case','frame','observer','suite','host','missing','result','fingerprint','model'])
def test_changed_symbol_view_reference_rejects(change):
    from tools.rust_migration.symbol_views_reference import validate_reference
    value=original()
    if change=='case':value['cases'][0]['input']={}
    elif change=='frame':value['frames'].pop()
    elif change=='observer':value['script_sha256']='a'*64
    elif change=='suite':value['test_states'][0]['outcome']='skipped'
    elif change=='host':value['runtime']['machine']='aarch64'
    elif change=='missing':del value['cases'][0]['result']
    elif change=='result':value['cases'][0]['result']['view']='changed'
    elif change=='fingerprint':value['reference_fingerprint']='a'*64
    else:value['source_artifacts']={}
    assert validate_reference(value)

def test_existing_capture_destination_never_runs_original_again(tmp_path,monkeypatch):
    from tools.rust_migration import symbol_views_reference as module
    from tools.rust_migration.reference import Reference
    monkeypatch.setattr(module,'verify_reference',lambda *a:[])
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:pytest.fail('original recaptured'))
    with pytest.raises(FileExistsError):module.capture(Reference.load(ROOT/'.ken/rust-migration/portable-reference'),tmp_path,Path('/unused'))
