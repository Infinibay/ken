"""Exercise actual native preparation and inference with explicit offline inputs."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.rust_migration.ettin_compare import compare

ROOT=Path(__file__).resolve().parents[1]


def prepared(name):
    path=Path(os.environ.get(name,''))
    assert path.is_absolute() and path.exists(),f'explicit prepared {name} required'
    return path


def test_native_ettin_prepares_and_scores_every_local_original_history(reference,tmp_path):
    result=compare(reference,prepared('KEN_ETTIN_PROBE'),prepared('KEN_ETTIN_SOURCE'),
                   prepared('KEN_ORT_LIBRARY'),tmp_path/'parity')
    assert result['passed'],result['errors']
    assert len(result['case_ids'])==23 and result['outside_checkout']
    assert result['native_children']==[]
    assert result['preparation']['fresh_cache'] is True
    assert result['preparation']['reused_without_source'] is True
    assert result['dependency_audit']['passed'] and result['core_dependency_audit']['passed']


def test_false_ettin_executable_cannot_count_as_native_preparation(reference,tmp_path):
    result=compare(reference,Path(shutil.which('true')).resolve(),prepared('KEN_ETTIN_SOURCE'),
                   prepared('KEN_ORT_LIBRARY'),tmp_path/'false')
    assert not result['passed'] and result['errors']


def test_ettin_probe_rejects_bad_input_and_reports_actual_empty_lazy_state(tmp_path):
    probe=prepared('KEN_ETTIN_PROBE')
    for request in [{},{'registration':{},'cases':[]},{'expected_scores':[29.]}]:
        result=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
        assert result.returncode==1 and not result.stdout and result.stderr
    fixtures=ROOT/'crates/ken-models/tests/fixtures/ettin'
    row=json.loads((fixtures/'manifest.json').read_text())['head']
    request={'registration':row['definition'],'source':str(fixtures/row['source']),
        'cache':str(tmp_path/'native-head'),
        'runtime_registration':json.loads((ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_text()),
        'library':str(tmp_path/'absent-core'),
        'cases':[{'id':'empty','options':{},'calls':[{'op':'score','query':'x','texts':[]}]}]}
    result=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=30)
    assert result.returncode==0 and not result.stderr,(result.stdout,result.stderr)
    value=json.loads(result.stdout)
    assert value['preparation']['fresh_cache'] is True
    assert value['preparation']['reused_without_source'] is True
    assert value['artifacts']['model.onnx']['sha256']==row['expected_graph']['sha256']
    assert value['runtime']['native_core'] is None
    assert value['results'][0]['session_loaded'] is False
    assert value['results'][0]['providers']==[]
    assert value['results'][0]['cpu_arena'] is None
    assert value['results'][0]['calls']==[{'scores':[], 'details':{
        'token_ms':0.,'inference_ms':0.,'truncated_documents':0,'pair_tokens':[]}}]
    request['source']=None
    result=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=30)
    assert result.returncode==0 and not result.stderr
    assert json.loads(result.stdout)['preparation']['fresh_cache'] is False
