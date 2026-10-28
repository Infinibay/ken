from pathlib import Path
import gzip,json
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_full_symbol_composition_original_is_complete():
    from tools.rust_migration.symbol_ranking_reference import FIXTURE,cases,validate_reference
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    assert len(cases())>=30 and not validate_reference(value)
    assert len({c['id']for c in cases()})==len(cases())
    assert sum(c['model']['kind']=='ettin'for c in cases())==3

def test_full_symbol_original_destination_cannot_be_overwritten(tmp_path):
    from tools.rust_migration.symbol_ranking_reference import capture
    with pytest.raises(FileExistsError):capture(None,tmp_path)

@pytest.mark.parametrize('change',['source','observer','source-api','inputs','input-answer','key','calls','assets','definition','runtime'])
def test_resealed_symbol_composition_original_rejects(change):
    from tools.rust_migration.symbol_ranking_reference import FIXTURE,validate_reference,digest
    value=json.loads(gzip.decompress((ROOT/FIXTURE).read_bytes()))
    if change=='source':value['reference_fingerprint']='0'*64
    elif change=='observer':value['script_sha256']='0'*64
    elif change=='source-api':value['original_source_sha256']='0'*64
    elif change=='inputs':value['cases'][0]['input']['physical']['files']={}
    elif change=='input-answer':value['cases'][0]['input']['expected']={}
    elif change=='key':value['cases'][0]['input']['keys'][0]['qualname']='foreign'
    elif change=='calls':value['cases'][0]['observations'][0]['calls']=[]
    elif change=='assets':value['artifacts']['model.onnx']['sha256']='0'*64
    elif change=='definition':value['definition']['foreign']=True
    else:value['runtime']['python']='3.14.0'
    value['observations_sha256']=digest(value)
    assert validate_reference(value)
