"""Independent native-process kills, recovery and original-format readback."""
import os
from pathlib import Path
import shutil
from tools.rust_migration.storage_recovery import verify_recovery,recovery_receipt_errors

def driver():
    probe=Path(os.environ.get('KEN_STORAGE_PROBE',''))
    assert probe.is_absolute() and probe.is_file(),'explicit prepared KEN_STORAGE_PROBE required'
    result=probe.with_name('storage_recovery_driver');assert result.is_file()
    return result

def test_native_storage_recovers_all_five_external_kill_histories_and_preserves_original_readability(reference,tmp_path):
    result=verify_recovery(reference,driver(),tmp_path/'recovery')
    assert result['passed'],result['errors']
    assert recovery_receipt_errors(result)==[]
    assert len(result['cases'])==5 and result['outside_checkout'] is True
    assert result['native_children']==[] and result['M2_accepted'] is False

def test_interpreted_or_empty_driver_cannot_certify_recovery(reference,tmp_path):
    shell=tmp_path/'fake';shell.write_text('#!/bin/sh\nexit 0\n');shell.chmod(0o755)
    for candidate in [Path(shutil.which('true')).resolve(),shell]:
        result=verify_recovery(reference,candidate,tmp_path/'receipts'/candidate.name)
        assert result['passed'] is False and result['errors']
