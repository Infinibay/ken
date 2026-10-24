"""Actual lint commands retain success/failure evidence before returning."""
import json,sys
from pathlib import Path
import pytest

def commands(failure=False):
    return {'fmt':[sys.executable,'-c','pass'],'clippy':[sys.executable,'-c',"print('    Finished `dev` profile [unoptimized] target(s) in 0.1s'); raise SystemExit("+('7'if failure else'0')+")"]}

def test_actual_lint_commands_bind_exit_and_log_before_verification(tmp_path):
    from tools.rust_migration.command_gates import run_lint_gates,lint_gate_errors
    expected=commands();run_lint_gates(tmp_path,expected)
    value=json.loads((tmp_path/'LINT.json').read_bytes())
    assert all(row['exit']==0 for row in value.values())
    assert not lint_gate_errors(tmp_path,expected)
    (tmp_path/'clippy.log').write_text('')
    assert lint_gate_errors(tmp_path,expected)

def test_failed_actual_lint_preserves_exit_and_cannot_be_accepted(tmp_path):
    from tools.rust_migration.command_gates import run_lint_gates,lint_gate_errors
    expected=commands(True)
    with pytest.raises(RuntimeError):run_lint_gates(tmp_path,expected)
    value=json.loads((tmp_path/'LINT.json').read_bytes())
    assert value['clippy']['exit']==7 and(tmp_path/'clippy.log').is_file()
    assert lint_gate_errors(tmp_path,expected)

def test_actual_general_command_gate_records_scoped_output_and_rejects_empty_work(tmp_path):
    from tools.rust_migration.command_gates import run_command_gates,command_gate_errors
    expected={'discovery':[sys.executable,'-c',"print('observed discovery')"]}
    run_command_gates(tmp_path,expected)
    assert(tmp_path/'discovery.log').read_text()=='observed discovery\n'
    assert not command_gate_errors(tmp_path,expected)
    with pytest.raises(ValueError):run_command_gates(tmp_path,{})
