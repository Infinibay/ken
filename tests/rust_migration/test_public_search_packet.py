"""Actual public process packets must remain independently verifiable."""
from pathlib import Path
import json, os, shutil
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_incomplete_public_packet_is_rejected(tmp_path):
    from tools.rust_migration.public_search_host import verify_capture
    assert verify_capture(tmp_path,ROOT)

def packet():
    return Path(os.environ['KEN_PUBLIC_SEARCH_PACKET'])

def test_actual_copied_public_cli_and_mcp_packet():
    from tools.rust_migration.public_search_host import verify_capture
    assert not verify_capture(packet(),ROOT)

@pytest.mark.parametrize('member',['INPUTS.json','SOURCES.json','BACKEND-BUILD.json','native/stdout','native/execution.json'])
def test_changed_public_packet_is_rejected(tmp_path,member):
    from tools.rust_migration.public_search_host import verify_capture
    copied=tmp_path/'packet';shutil.copytree(packet(),copied)
    path=copied/member
    if path.suffix=='.json':path.write_text('{}')
    else:path.write_bytes(b'not the actual public caller output')
    assert verify_capture(copied,ROOT)

def test_resealed_public_resource_answer_injection_is_rejected(tmp_path):
    from tools.rust_migration.public_search_host import verify_capture
    copied=tmp_path/'packet';shutil.copytree(packet(),copied)
    path=copied/'INPUTS.json';value=json.loads(path.read_text())
    value['files']['inputs/answers.json']=dict(source='/answers',artifact=dict(bytes=2,sha256='0'*64))
    path.write_text(json.dumps(value))
    assert verify_capture(copied,ROOT)
