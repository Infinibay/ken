"""A success flag cannot replace complete final regression output."""
from tools.rust_migration.integration_validate import rust_gate_errors


def test_every_discovered_rust_case_must_have_one_actual_success():
    discovery='alpha: test\nbeta: test\n2 tests, 0 benchmarks\n'
    actual='test alpha ... ok\ntest beta ... ok\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n'
    assert rust_gate_errors(discovery,actual)==[]
    for bad in [actual.replace('test beta ... ok\n',''),actual.replace('beta ... ok','beta ... ignored'),
                actual+ 'test alpha ... ok\n','{"passed":true}',actual.replace('0 ignored','1 ignored')]:
        assert rust_gate_errors(discovery,bad)
    assert rust_gate_errors(discovery+'gamma: test\n',actual)


def test_missing_platforms_or_raw_gates_cannot_award_m2(tmp_path):
    import json
    from pathlib import Path
    from tools.rust_migration.integration_validate import aggregate_integration
    repo=Path(__file__).resolve().parents[2]
    (tmp_path/'INDEX.json').write_text(json.dumps({'format':'ken-model-integration-acceptance/1','passed':True,'M2_accepted':True}))
    report=aggregate_integration(tmp_path,repo)
    assert report['passed'] is False and report['M2_accepted'] is False and report['errors']


def test_resealing_a_changed_predecessor_manifest_cannot_replace_the_pinned_proof(tmp_path):
    import json
    from pathlib import Path
    from tools.rust_migration.integration_validate import verify_predecessors,PREDECESSORS
    for name in PREDECESSORS:
        directory=tmp_path/name;directory.mkdir(parents=True)
        (directory/'FILES.json').write_text(json.dumps({'files':[],'passed':True}))
    assert verify_predecessors(tmp_path)


def test_native_child_harness_and_interleaved_build_output_keep_parent_case_accounting():
    discovery='parent: test\nhelper: test\n'
    actual=('test parent ... \nrunning 1 test\ntest helper ... ok\n'
        'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out; finished in 0.0s\n'
        'ok\ntest helper ...     Finished `dev` profile\nok\n'
        'test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n')
    assert rust_gate_errors(discovery,actual)==[]
    assert rust_gate_errors(discovery,actual.replace('ok\ntest helper','FAILED\ntest helper',1))


def test_targeted_junit_composition_preserves_unaffected_cases_and_rejects_unrelated_replacements(tmp_path):
    import pytest
    from tools.rust_migration.integration_validate import compose_python_junit
    from tools.rust_migration.receipts import junit_states
    original=tmp_path/'full.xml';supplement=tmp_path/'supplement.xml';combined=tmp_path/'combined.xml'
    original.write_text('<testsuite><testcase classname="legacy" name="a"/><testcase classname="tools" name="b"><failure/></testcase></testsuite>')
    supplement.write_text('<testsuite><testcase classname="tools" name="b"/><testcase classname="tools" name="c"/></testsuite>')
    allowed={'tools::b','tools::c'}
    compose_python_junit(original,supplement,combined,allowed)
    assert junit_states(combined)=={'legacy::a':'passed','tools::b':'passed','tools::c':'passed'}
    supplement.write_text('<testsuite><testcase classname="legacy" name="a"/></testsuite>')
    with pytest.raises(ValueError):compose_python_junit(original,supplement,combined,allowed)
    supplement.write_text('<testsuite><testcase classname="tools" name="b"><skipped/></testcase><testcase classname="tools" name="c"/></testsuite>')
    with pytest.raises(ValueError):compose_python_junit(original,supplement,combined,allowed)


def test_linux_audit_command_itself_must_trace_both_exec_syscalls_and_network(tmp_path):
    import json,shutil
    from pathlib import Path
    from tools.rust_migration.integration_replay import replay_transformer_profile,replay_role
    repo=Path(__file__).resolve().parents[2];fixtures=repo/'crates/ken-models/tests/fixtures/factory-integration'
    for name in('linux-bge-cpu-bfloat16','linux-potion'):
        root=tmp_path/name;shutil.copytree(fixtures/name,root)
        path=root/'observed.receipt.json';receipt=json.loads(path.read_bytes())
        receipt['command']=[part.replace('trace=execve,execveat,connect','trace=execve')for part in receipt['command']]
        path.write_text(json.dumps(receipt))
        errors=replay_transformer_profile(root,repo,'linux',0)if name.startswith('linux-bge')else replay_role(root,repo,'linux','potion','offline')
        assert errors,'Declared audit flags cannot replace the actual tracer command'
