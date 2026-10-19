"""Exercise native preparation and real translation in independent processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.rust_migration.translation_compare import compare

ROOT=Path(__file__).resolve().parents[1]


def prepared(name):
    path=Path(os.environ.get(name,''))
    assert path.is_absolute() and path.exists(),f'explicit prepared {name} required'
    return path


def test_native_translation_prepares_and_runs_all29_local_original_histories(reference,tmp_path):
    result=compare(reference,prepared('KEN_TRANSLATION_PROBE'),prepared('KEN_TRANSLATION_SOURCE'),tmp_path/'parity')
    assert result['passed'],result['errors']
    assert len(result['case_ids'])==29 and result['outside_checkout'] is True
    assert result['native_children']==[] and result['dependency_audit']['passed'] is True
    assert result['preparation']['fresh_cache'] is True
    assert result['preparation']['reused_without_source'] is True
    assert result['native_identity']['observed_replicas']==1
    assert result['native_identity']['ctranslate2_source']=='4.8.2'


def test_false_or_interpreted_translation_probe_cannot_certify_preparation(reference,tmp_path):
    shell=tmp_path/'fake-probe';shell.write_text('#!/bin/sh\nexit 0\n');shell.chmod(0o755)
    for candidate in [Path(shutil.which('true')).resolve(),shell]:
        result=compare(reference,candidate,prepared('KEN_TRANSLATION_SOURCE'),tmp_path/'receipts'/candidate.name)
        assert not result['passed'] and result['errors']


def test_native_probe_rejects_supplied_expectations_and_keeps_real_english_path_lazy(tmp_path):
    probe=prepared('KEN_TRANSLATION_PROBE')
    for request in [{},{'registration':{},'cases':[]},{'expected_outputs':['text']}]:
        child=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
        assert child.returncode==1 and child.stderr and not child.stdout
    fixtures=ROOT/'crates/ken-models/tests/fixtures/translation/tiny'
    tiny=json.loads((fixtures/'manifest.json').read_text())
    cache=tmp_path/tiny['definition']['derived']['revision']
    request={'registration':tiny['definition'],'source':str(fixtures/tiny['source']),'cache':str(cache),
             'cases':[{'id':'english','queries':['find the input parser','']} ]}
    child=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
    assert child.returncode==0 and not child.stderr,(child.stdout,child.stderr)
    actual=json.loads(child.stdout)
    assert actual['preparation']['fresh_cache'] is True
    assert actual['preparation']['reused_without_source'] is True
    assert actual['preparation']['artifacts']==tiny['definition']['derived']['artifacts']
    assert actual['results'][0]['actual_runtime'] is None
    assert [c['output'] for c in actual['results'][0]['calls']]==['find the input parser','']
    assert all(c['trace']=={} and c['runtime_loaded'] is False for c in actual['results'][0]['calls'])
    request['source']=None
    child=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
    assert child.returncode==0 and not child.stderr
    assert json.loads(child.stdout)['preparation']['fresh_cache'] is False
