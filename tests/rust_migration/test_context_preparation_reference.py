from pathlib import Path
import gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_original_context_preparation_histories_are_complete_and_authenticated():
    from tools.rust_migration.context_preparation_reference import FIXTURE,cases,validate_reference
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    assert len(cases())>=24 and len({c['id']for c in cases()})==len(cases())
    assert not validate_reference(value)

def test_context_preparation_original_destination_is_never_overwritten(tmp_path):
    from tools.rust_migration.context_preparation_reference import capture
    with pytest.raises(FileExistsError):capture(None,tmp_path)

@pytest.mark.parametrize('change',['source','observer','api','inputs','answer-input','physical','actions','calls','runtime','registration'])
def test_resealed_original_context_preparation_rejects_tampering(change):
    from tools.rust_migration.context_preparation_reference import FIXTURE,validate_reference,digest
    v=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    if change=='source':v['reference_fingerprint']='0'*64
    elif change=='observer':v['script_sha256']='0'*64
    elif change=='api':v['original_source_sha256']='0'*64
    elif change=='inputs':v['inputs_sha256']='0'*64
    elif change=='answer-input':v['cases'][0]['input']['expected']={}
    elif change=='physical':v['cases'][0]['input']['physical']['files']={}
    elif change=='actions':v['cases'][0]['input']['actions']=[]
    elif change=='calls':v['cases'][0]['events'][0]['calls']=[]
    elif change=='runtime':v['runtime']['python']='3.14.0'
    else:v['definition']['model_id']='foreign'
    v['observations_sha256']=digest(v)
    assert validate_reference(v)
