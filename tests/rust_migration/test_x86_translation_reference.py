"""The x86 oracle is independent data, never the existing ARM expectations."""
from pathlib import Path
import copy,json,shutil
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_x86_reference_preserves_all_twenty_nine_original_histories():
    from tools.rust_migration.x86_translation_reference import load,validate
    value=load(ROOT)
    assert not validate(value)
    assert (value['platform'],value['architecture'])==('Linux','x86_64')
    assert len(value['cases'])==len(value['results'])==29
    cold=value['results'][0]['calls'][0]
    assert cold['output']=='Where are names normalized?'
    assert cold['runtime_loaded']is False and cold['trace']=={}
    assert any(call['trace'].get('hypotheses')for row in value['results']for call in row['calls'])

def test_missing_x86_reference_cannot_fall_back_to_arm(tmp_path):
    from tools.rust_migration.x86_translation_reference import load
    with pytest.raises(ValueError,match='preserved x86 translation'):
        load(tmp_path)

@pytest.mark.parametrize('change',['architecture','runtime','source','definition','inputs','result-order','calls','backend'])
def test_resealed_foreign_or_incomplete_x86_histories_are_rejected(change):
    from tools.rust_migration.x86_translation_reference import load,validate,digest
    value=copy.deepcopy(load(ROOT))
    if change=='architecture':value['architecture']='aarch64'
    elif change=='runtime':value['oracle']['runtime']['ctranslate2']='4.8.3'
    elif change=='source':value['oracle']['module_hashes']['ken.retrieval.query_expansion']='0'*64
    elif change=='definition':value['definition']['derived']['revision']='foreign'
    elif change=='inputs':value['cases'][0]['queries']=['foreign query']
    elif change=='result-order':value['results'].reverse()
    elif change=='calls':value['results'][0]['calls']=[]
    else:
        next(row for row in value['results']if row['actual_runtime'])['actual_runtime']['compute_type']='float32'
    value['results_sha256']=digest(value['results'])
    assert validate(value)

def test_changed_compressed_reference_is_rejected_before_comparison(tmp_path):
    from tools.rust_migration.x86_translation_reference import FIXTURE,load
    path=tmp_path/FIXTURE;path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/FIXTURE,path)
    raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
    with pytest.raises(ValueError,match='preserved x86 translation'):
        load(tmp_path)

def test_existing_observations_cannot_be_overwritten(tmp_path):
    from tools.rust_migration.x86_translation_reference import capture
    out=tmp_path/'original';out.mkdir();(out/'records.jsonl').write_bytes(b'preserved\n')
    with pytest.raises(FileExistsError):capture(None,None,out)
    assert (out/'records.jsonl').read_bytes()==b'preserved\n'

def test_non_x86_host_is_rejected_before_original_execution(tmp_path,monkeypatch):
    from tools.rust_migration import x86_translation_reference as observer
    monkeypatch.setattr(observer.platform,'machine',lambda:'aarch64')
    out=tmp_path/'original'
    with pytest.raises(ValueError,match='Linux x86_64'):observer.capture(None,None,out)
    assert not out.exists()
