"""Frozen original parser observations are independent, complete and reusable."""
from dataclasses import replace
import json,os,sys
from pathlib import Path
import pytest
from tools.rust_migration.reference import Reference
from tools.rust_migration.parser_reference import capture_parser_reference,parser_owner_hashes,validate_parser_reference

REPO=Path(__file__).resolve().parents[2]


def reference():
    return replace(Reference.load(Path(os.environ.get('KEN_RUST_REFERENCE',REPO/'.ken/rust-migration/m2-optional/reference-final-t9'))),python=Path(sys.executable).absolute())


def test_owner_drift_fails_before_importing_or_running_original(tmp_path):
    original=reference();fake=tmp_path/'fake';fake.mkdir()
    for name in parser_owner_hashes(REPO):
        target=fake/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((original.root/name).read_bytes())
    (fake/'src/ken/parsers/python.py').write_text('# changed')
    with pytest.raises(ValueError,match='changed original parser'):
        capture_parser_reference(replace(original,root=fake),tmp_path/'out',repo=REPO)


@pytest.fixture(scope='module')
def captured(tmp_path_factory):
    out=Path(os.environ.get('KEN_PARSER_REFERENCE_OUT',tmp_path_factory.mktemp('parser-reference')/'capture'))
    return out,capture_parser_reference(reference(),out,repo=REPO)


def test_actual_original_parser_suite_and_all_twenty_grammars_are_captured_once(captured):
    out,result=captured
    assert validate_parser_reference(result)==[]
    assert result['test_execution']['exit']==0 and result['calls']>=200
    assert len(result['coverage'])==20
    assert all(row['cases']>=3 for row in result['coverage'].values())
    assert any(c['input']['language']=='cpp' and len(c['input']['source_hex'])>10000 for c in result['cases'])
    assert any(c['input']['hint'].endswith('.tsx') for c in result['cases'])
    # Reusing the exact captured identity must not invoke the interpreter again.
    second=capture_parser_reference(replace(reference(),python=Path('/nonexistent/python')),out,repo=REPO)
    assert second==result


def test_changed_capture_inventory_is_rejected(captured):
    # Reuse the session capture when available; this never reruns the old suite.
    out,_=captured
    result=json.loads((out/'reference.json').read_bytes())
    result['cases'].pop()
    assert validate_parser_reference(result)
