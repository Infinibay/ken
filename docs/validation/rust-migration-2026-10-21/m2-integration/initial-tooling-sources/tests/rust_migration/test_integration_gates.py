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
