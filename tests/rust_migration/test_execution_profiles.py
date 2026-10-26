from pathlib import Path
import json,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='session')
def cpu_probe(tmp_path_factory):
    out=tmp_path_factory.mktemp('x86-cpu')/'probe'
    child=subprocess.run(['rustc','--edition=2024',str(ROOT/'crates/ken-models/tests/support/x86_features_probe.rs'),'-o',str(out)],capture_output=True,text=True)
    assert child.returncode==0,child.stderr
    return out

def test_effective_features_are_explicit_booleans_without_cpu_model_guess(cpu_probe):
    from tools.rust_migration.execution_profiles import capabilities
    value=capabilities(cpu_probe)
    assert set(value)=={'format','target','features'}and value['target']=='linux-x86_64'
    assert all(type(x)is bool for x in value['features'].values())
    assert value['features']['avx2'] is True
    assert 'cpu_model'not in value


def test_complete_original_inputs_are_fixed_and_answer_free():
    from tools.rust_migration.execution_profiles import inputs
    value=inputs(ROOT)
    assert len(value['context'])==20 and len(value['alignment'])==245
    assert all(set(c)=={'id','kind','input'}for c in value['alignment'])
    assert all('result'not in c for c in value['context'])


def test_missing_capture_and_attempted_overwrite_reject(tmp_path):
    from tools.rust_migration.execution_profiles import verify_capture,assert_fresh
    assert verify_capture(tmp_path,ROOT)
    with pytest.raises(FileExistsError):assert_fresh(tmp_path)


def test_alignment_harness_calls_original_without_pytest_or_native_answers():
    from tools.rust_migration.execution_profiles import ALIGNMENT_OBSERVER
    assert 'from ken.retrieval.alignment import TermAlignment'in ALIGNMENT_OBSERVER
    assert 'pytest.main('not in ALIGNMENT_OBSERVER and 'numeric_owner_probe'not in ALIGNMENT_OBSERVER
