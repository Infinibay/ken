"""Real native policy execution, independent of model data and expected outputs."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.rust_migration.policy_compare import RUNTIME,compare_policy


def prepared_probe():
    value=os.environ.get('KEN_POLICY_PROBE','');probe=Path(value)
    assert value and probe.is_absolute() and probe.is_file() and os.access(probe,os.X_OK), 'explicit prepared KEN_POLICY_PROBE required'
    return probe


def test_native_model_policy_matches_all1292_original_histories_without_model_assets(reference,tmp_path):
    result=compare_policy(reference,prepared_probe(),tmp_path/'parity')
    assert result['passed'],result['errors']
    assert len(result['case_ids'])==1292 and len(result['prompt_models'])==23
    assert result['runtime']==RUNTIME and result['runtime']['model_runtime_needed'] is False
    assert result['outside_checkout'] is True and result['native_children']==[] and result['stderr']==''
    assert result['dependency_audit']['passed'] is True and result['M2_accepted'] is False


def test_false_or_interpreted_policy_process_cannot_certify_native_decisions(reference,tmp_path):
    shell=tmp_path/'fake-probe';shell.write_text('#!/bin/sh\nexit 0\n');shell.chmod(0o755)
    for probe in [Path(shutil.which('true')).resolve(),shell]:
        row=compare_policy(reference,probe,tmp_path/'receipts'/probe.name)
        assert row['passed'] is False and row['errors']


def test_native_policy_request_rejects_expected_injection_and_wrong_types_and_preserves_raw_overrides(tmp_path):
    probe=prepared_probe()
    valid={'cases':[{'id':'raw','input':{'user_config':{'default_model':' user/default '},
        'environment':'\0','project_visible':True,'facts':{'recorded_model':None,'file_vectors_present':False},
        'forced_variants':[None,'','forced/model',' ']}}],'prompts':['intfloat/e5-base']}
    child=subprocess.run([str(probe)],input=json.dumps(valid),text=True,capture_output=True,timeout=10)
    assert child.returncode==0 and not child.stderr,(child.stdout,child.stderr)
    actual=json.loads(child.stdout)
    assert actual['results']==[{'id':'raw','recommended':' user/default ',
        'project':{'model':'\0','initial_pin':{'model':'\0','document_space':2}},
        'active':['\0','\0','forced/model',' '],'upgrade':None}]
    assert actual['prompts']==[{'model':'intfloat/e5-base','query':'query: ','passage':'passage: ','asymmetric':True}]
    for request in [{},{'expected_outputs':['forged']},valid|{'expected':{}},
                    {'cases':valid['cases'],'prompts':[1]},
                    {'cases':[{'id':'bad','input':{'facts':{'file_vectors_present':0}}}],'prompts':[]}]:
        child=subprocess.run([str(probe)],input=json.dumps(request),text=True,capture_output=True,timeout=10)
        assert child.returncode==1 and child.stderr and not child.stdout
