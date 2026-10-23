"""Saved native bytes, not declared success flags, authenticate source proofs."""
import json
import os
from pathlib import Path

import pytest

from tools.rust_migration.source_evidence import verify_source_capture,aggregate_source_matrix
from tools.rust_migration.source_validate import capture_native_sources,source_identity

REPO=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('mutation',['stdout','request','host','integrity','missing'])
def test_actual_native_capture_binding_rejects_altered_raw_artifacts(tmp_path,mutation):
    target=Path(os.environ.get('CARGO_TARGET_DIR',str(REPO/'.ken/rust-migration/m2-fastembed/target-final-ci')))
    probe=target/'release/examples/source_probe'
    reference={'definitions':[{'id':'one','files':{'a.py':''},'scopes':['.']}],
        'cases':[{'id':'one','walks':[{'scope':'.','entries':[{'path':'a.py','is_dir':False}],'files':['a.py']}]}]}
    folder=tmp_path/'capture';actual=capture_native_sources(probe,reference,REPO,folder)
    sources=source_identity(REPO)
    assert verify_source_capture(folder,reference,sources,actual['native_sha256'])==[]
    if mutation=='stdout':
        path=folder/'observations/one/00/stdout.json';data=json.loads(path.read_bytes());data['entries'][0]['path']='other.py';path.write_text(json.dumps(data))
    elif mutation=='request':
        path=folder/'observations/one/00/inputs.json';data=json.loads(path.read_bytes());data['scope']='other';path.write_text(json.dumps(data))
    elif mutation=='host':
        path=folder/'observations/one/00/execution.json';data=json.loads(path.read_bytes());data['native_sha256']='f'*64;path.write_text(json.dumps(data))
    elif mutation=='integrity':
        path=folder/'integrity/stdout.json';data=json.loads(path.read_bytes());data['errors'].clear();path.write_text(json.dumps(data))
    else:(folder/'observations/one/00/execution.json').unlink()
    assert verify_source_capture(folder,reference,sources,actual['native_sha256']),mutation


def test_missing_platforms_and_raw_execution_cannot_award_source_acceptance(tmp_path):
    (tmp_path/'INDEX.json').write_text(json.dumps({'passed':True,'M3a_accepted':True}))
    result=aggregate_source_matrix(tmp_path,REPO)
    assert result['passed']is False and result['M3a_accepted']is False and result['M3_accepted']is False
    assert result['errors']
