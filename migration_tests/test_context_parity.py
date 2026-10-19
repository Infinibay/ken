"""Real contextual native process, with explicit prepared data and executable."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.rust_migration.context_compare import compare

ROOT=Path(__file__).resolve().parents[1]


def prepared(name):
    value=Path(os.environ.get(name,''))
    assert value.is_absolute() and value.exists(),f'explicit prepared {name} required'
    return value


def test_native_context_process_matches_every_local_original_history(reference,tmp_path):
    result=compare(reference,prepared('KEN_CONTEXT_PROBE'),prepared('KEN_CONTEXT_SNAPSHOT'),
                   prepared('KEN_ORT_LIBRARY'),tmp_path/'parity')
    assert result['passed'],result['errors']
    assert len(result['case_ids'])==20 and result['outside_checkout']
    assert result['native_children']==[]
    assert result['dependency_audit']['passed'] and result['core_dependency_audit']['passed']


def test_false_context_executable_is_not_an_encoder(reference,tmp_path):
    result=compare(reference,Path(shutil.which('true')).resolve(),prepared('KEN_CONTEXT_SNAPSHOT'),
                   prepared('KEN_ORT_LIBRARY'),tmp_path/'false')
    assert not result['passed'] and result['errors']


def test_context_probe_reports_actual_lazy_state_and_rejects_bad_input(tmp_path):
    probe=prepared('KEN_CONTEXT_PROBE')
    for request in [{},{'registration':{},'snapshot':'absent'}]:
        result=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
        assert result.returncode==1 and not result.stdout and result.stderr
    request={'registration':json.loads((ROOT/'src/ken/embedder/data/code-context-int8.json').read_text()),
        'snapshot':str(prepared('KEN_CONTEXT_SNAPSHOT')),
        'runtime_registration':json.loads((ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_text()),
        'library':str(tmp_path/'no-core'),
        'cases':[{'id':'empty','prepare':False,'calls':[{'op':'passages','texts':[]}]}]}
    result=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=30)
    assert result.returncode==0 and not result.stderr
    value=json.loads(result.stdout)
    assert value['runtime']['native_core'] is None
    assert value['results'][0]['calls']==[[]] and value['results'][0]['session_loaded'] is False
    assert value['results'][0]['providers']==[]
