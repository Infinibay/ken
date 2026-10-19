"""Real independent native storage execution; no missing-runtime skips."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from tools.rust_migration.storage_compare import RUNTIME,compare_storage

def prepared_probe():
    value=os.environ.get('KEN_STORAGE_PROBE','');probe=Path(value)
    assert value and probe.is_absolute() and probe.is_file() and os.access(probe,os.X_OK),'explicit prepared KEN_STORAGE_PROBE required'
    return probe

def test_native_storage_matches23_valid_original_histories_and9_integrity_corrections(reference,tmp_path):
    out=tmp_path/'parity';row=compare_storage(reference,prepared_probe(),out)
    assert row['passed'],row['errors']
    assert len(row['case_ids'])==32 and row['compatibility_count']==23 and row['correction_count']==9
    assert row['runtime']==RUNTIME and row['outside_checkout'] is True
    assert row['native_children']==[] and row['stderr']=='' and row['M2_accepted'] is False
    assert (out/'cargo-tree.log').read_text().startswith('ken-store ')

def test_false_or_interpreted_storage_process_cannot_certify_parity(reference,tmp_path):
    shell=tmp_path/'fake';shell.write_text('#!/bin/sh\nexit 0\n');shell.chmod(0o755)
    for probe in [Path(shutil.which('true')).resolve(),shell]:
        row=compare_storage(reference,probe,tmp_path/'receipts'/probe.name)
        assert row['passed'] is False and row['errors']

def test_storage_protocol_rejects_expected_source_setup_injection_and_executes_raw_metadata():
    probe=prepared_probe();valid={'cases':[{'id':'metadata','input':{'op':'metadata','values':['','\0é']}}]}
    child=subprocess.run([str(probe)],input=json.dumps(valid),text=True,capture_output=True,timeout=10)
    assert child.returncode==0 and child.stderr==''
    assert json.loads(child.stdout)['results'][0]['output']=={'values':['','\0é'],'missing':None,'default':'fallback'}
    for bad in [{},valid|{'expected':{}},valid|{'source_setup':{}},{'cases':[{'id':'x','input':{'op':'metadata','values':[False]}}]}, {'cases':[valid['cases'][0],valid['cases'][0]]}]:
        child=subprocess.run([str(probe)],input=json.dumps(bad),text=True,capture_output=True,timeout=10)
        assert child.returncode==1 and child.stderr and child.stdout==''
