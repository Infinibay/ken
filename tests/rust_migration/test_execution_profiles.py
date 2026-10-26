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

@pytest.fixture
def original(tmp_path):
    import os,shutil
    source=Path(os.environ.get('KEN_EXECUTION_PROFILE_ORIGINAL',ROOT/'.ken/rust-migration/execution-profiles/local-original-ready'))
    target=tmp_path/'original';shutil.copytree(source,target);return target

def test_actual_full_original_capture_is_verified(original):
    from tools.rust_migration.execution_profiles import verify_capture
    assert not verify_capture(original,ROOT)

@pytest.mark.parametrize('change',['capability','context-input-answer','alignment-input-answer','context-value','source','threads'])
def test_resealed_original_capture_rejects_wrong_contract(original,change):
    from tools.rust_migration.execution_profiles import verify_capture,fingerprint
    from tools.rust_migration.native_json import identity
    manifest=original/'CAPTURE.json';value=json.loads(manifest.read_bytes())
    if change=='capability':
        value['capabilities']['features']['avx2']=1;value['descriptors']['context']['features']['avx2']=1;value['ids']['context']=fingerprint(value['descriptors']['context'])
    else:
        name='context-inputs.json'if change=='context-input-answer'else'alignment-inputs.json'if change=='alignment-input-answer'else'context.json'if change=='context-value'else'alignment.json'
        path=original/name;data=json.loads(path.read_bytes())
        if change.endswith('input-answer'):data['expected']={}
        elif change=='context-value':data['results'][1]['calls'][1][0]+=1
        elif change=='source':data['source_sha256']='0'*64
        else:data['blas']['threads']=True
        path.write_text(json.dumps(data));value['files'][name]=identity(path)
    manifest.write_text(json.dumps(value));assert verify_capture(original,ROOT)
