"""Audit retained first original captures; independent of ongoing native gates."""
from pathlib import Path
import json,os,shutil
import pytest
ROOT=Path(__file__).resolve().parents[2]

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

def test_registered_full_profiles_preserve_legacy_and_all_inputs(tmp_path):
    from tools.rust_migration.execution_registry import register,select,LEGACY_CONTEXT,LEGACY_ALIGNMENT
    from tools.rust_migration.native_json import identity
    files=[LEGACY_CONTEXT,LEGACY_ALIGNMENT,'crates/ken-retrieval/tests/fixtures/numeric-inputs-alignment.json','src/ken/embedder/data/code-context-int8.json','crates/ken-models/resources/onnx-runtime-libraries.json']
    for name in files:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    before={name:identity(tmp_path/name)for name in files}
    captures=[Path(os.environ.get('KEN_EXECUTION_PROFILE_ORIGINAL',ROOT/'.ken/rust-migration/execution-profiles/local-original-ready')),*sorted((ROOT/'.ken/rust-migration/execution-profiles/ci').glob('replica-*'))]
    index=register(tmp_path,captures)
    assert {kind:len(rows)for kind,rows in index['families'].items()}==dict(context=2,alignment=2)
    assert before=={name:identity(tmp_path/name)for name in files}
    for kind,rows in index['families'].items():
        for row in rows:
            _,original=select(tmp_path,kind,row['descriptor'])
            assert len(original['cases'])==(20 if kind=='context'else 245)
    with pytest.raises(ValueError):register(tmp_path,captures)

def test_frozen_source_inventory_is_authenticated_instead_of_declared(tmp_path):
    from tools.rust_migration.execution_profiles import authenticate_frozen,FP
    from tools.rust_migration.reference import Reference
    original=Reference.load(ROOT/'.ken/rust-migration/portable-reference')
    authenticate_frozen(original)
    manifest=json.loads(original.manifest_path.read_bytes())
    manifest['files'][0]['sha256']='0'*64
    (tmp_path/'reference-manifest.json').write_text(json.dumps(manifest))
    assert Reference.load(tmp_path).fingerprint==FP
    with pytest.raises(ValueError,match='fingerprint'):authenticate_frozen(Reference.load(tmp_path))


def test_resealed_retained_observer_cannot_claim_the_approved_script(original):
    from tools.rust_migration.execution_profiles import verify_capture
    from tools.rust_migration.native_json import identity
    path=original/'alignment-observer.py';path.write_text('raise SystemExit("changed observer")\n')
    manifest=original/'CAPTURE.json';record=json.loads(manifest.read_bytes());record['files']['alignment-observer.py']=identity(path);manifest.write_text(json.dumps(record))
    assert verify_capture(original,ROOT)
