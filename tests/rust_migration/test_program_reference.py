"""The program oracle observes actual original calls and reuses sealed captures."""
from pathlib import Path
import os
from dataclasses import replace
from tools.rust_migration.program_reference import capture_program_reference,validate_program_reference
from tools.rust_migration.reference import Reference
REPO=Path(__file__).resolve().parents[2]

def test_actual_common_model_and_annotation_calls_are_captured_and_cached(tmp_path):
    reference=Reference.load(Path(os.environ.get('KEN_RUST_REFERENCE',REPO/'.ken/rust-migration/m2-optional/reference-final-t9')))
    out=Path(os.environ.get('KEN_PROGRAM_REFERENCE_OUT',tmp_path/'reference'))
    observed=capture_program_reference(reference,out,repo=REPO)
    assert validate_program_reference(observed)==[]
    assert len(observed['programs'])>=50 and len(observed['types'])>=70
    assert len(observed['discovered'])>=100
    assert all(state['outcome']=='passed'for state in observed['test_states'])
    cached=capture_program_reference(replace(reference,python=Path('/missing/python')),out,repo=REPO)
    assert cached==observed

def test_changed_complete_program_and_original_failure_are_not_validated():
    assert validate_program_reference({'format':'other'})
