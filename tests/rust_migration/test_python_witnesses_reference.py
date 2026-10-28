from pathlib import Path
import copy,gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_python_original_corpus_is_complete_and_validated():
    from tools.rust_migration.python_witnesses_reference import FIXTURE,cases,validate_reference
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    assert len(cases())>=100 and not validate_reference(value)
    assert len({c['id']for c in cases()})==len(cases())

def test_existing_original_destination_rejects_before_loading_any_source(tmp_path):
    from tools.rust_migration.python_witnesses_reference import capture
    with pytest.raises(FileExistsError):capture(None,tmp_path)

@pytest.mark.parametrize('change',['source','source-code','observer','inputs','input-answer','result','owners','runtime'])
def test_changed_or_resealed_original_contract_rejects(change):
    from tools.rust_migration.python_witnesses_reference import FIXTURE,validate_reference,digest
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    if change=='source':value['reference_fingerprint']='0'*64
    elif change=='source-code':value['original_source_sha256']='0'*64
    elif change=='observer':value['script_sha256']='0'*64
    elif change=='inputs':value['cases'][0]['input']['files']={}
    elif change=='input-answer':value['cases'][0]['input']['expected']={}
    elif change=='result':value['cases'][0]['result'][0]['warm']=['invented']
    elif change=='owners':value['cases'][0]['input']['owners']=[]
    else:value['runtime']['python']='3.14.0'
    value['observations_sha256']=digest(value)
    assert validate_reference(value)
