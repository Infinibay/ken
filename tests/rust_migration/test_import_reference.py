"""Resolution references come from real original callers and retain complete inputs."""
from dataclasses import replace
import json, os, sys
from pathlib import Path
import pytest
from tools.rust_migration.reference import Reference
from tools.rust_migration.import_reference import capture_import_reference, import_owner_hashes, validate_import_reference

REPO=Path(__file__).resolve().parents[2]
def reference():
    return replace(Reference.load(Path(os.environ.get('KEN_RUST_REFERENCE',REPO/'.ken/rust-migration/m2-optional/reference-final-t9'))),python=Path(sys.executable).absolute())

def test_import_owner_drift_rejected_before_original_execution(tmp_path):
    old=reference();root=tmp_path/'original';root.mkdir()
    for name in import_owner_hashes(REPO):
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((old.root/name).read_bytes())
    (root/'src/ken/jsresolve.py').write_text('# altered original')
    with pytest.raises(ValueError,match='original import owner changed'):
        capture_import_reference(replace(old,root=root),tmp_path/'out',repo=REPO)

@pytest.fixture(scope='module')
def captured(tmp_path_factory):
    out=Path(os.environ.get('KEN_IMPORT_REFERENCE_OUT',tmp_path_factory.mktemp('imports')/'capture'))
    return out,capture_import_reference(reference(),out,repo=REPO)

def test_real_indexer_callers_and_missing_target_cases_are_captured_once(captured):
    out,value=captured
    assert validate_import_reference(value)==[]
    assert len(value['discovered'])>=30
    assert any(r['tests']for r in value['cases'])
    assert any(None in r['structural_targets']for r in value['cases'])
    assert any(r['input']['configs']is not None for r in value['cases'])
    assert capture_import_reference(replace(reference(),python=Path('/missing/python')),out,repo=REPO)==value

def test_lost_reordered_or_modified_reference_case_is_rejected(captured):
    out,_=captured;value=json.loads((out/'reference.json').read_bytes())
    value['cases'].pop()
    assert validate_import_reference(value)
