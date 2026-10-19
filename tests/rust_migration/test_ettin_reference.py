"""Expectations come from frozen original preparation and real tiny ONNX graphs."""
import json
from pathlib import Path
import shutil

import pytest

from tools.rust_migration.reference import freeze_reference

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture
def original(tmp_path):
    source=tmp_path/'source'
    shutil.copytree(ROOT/'src',source/'src',ignore=shutil.ignore_patterns('__pycache__'))
    (source/'tests/retrieval').mkdir(parents=True)
    for name in ['test_reranker_head.py','test_neural_reranker.py']:
        shutil.copy2(ROOT/'tests/retrieval'/name,source/'tests/retrieval'/name)
    return freeze_reference(source,tmp_path/'frozen')


def test_frozen_ettin_fixtures_keep_exact_preparation_and_pair_policy(original,tmp_path):
    from tools.rust_migration.ettin_fixtures import generate
    from tools.rust_migration.ettin_reference import capture
    reference=original
    fixtures=generate(reference,tmp_path/'fixtures')
    assert fixtures['original_helpers_verified'] is True
    head=fixtures['head'];pair=fixtures['pair']
    assert head['original_preparation_verified'] is True
    assert abs(head['original_scalar_score']-head['independent_scalar_score'])<4e-6
    assert head['expected_graph']['sha256']==head['definition']['graph']['sha256']
    cases=[{'id':'empty','options':{},'calls':[{'op':'score','query':'x','texts':[]}]},
           {'id':'ordered','options':{},'calls':[{'op':'score','query':'x','texts':['y','x x x','x','y y']}]},
           {'id':'truncate','options':{'max_tokens':512},'calls':[{'op':'score','query':'x','texts':['x '*1000]}]}]
    result=capture(reference,Path(pair['source']),tmp_path/'original.json',definition=pair['definition'],
                   prepared=Path(pair['prepared']),cases=cases)
    assert result['oracle']['frozen_import'] is True
    empty,ordered,truncated=result['results']
    assert empty['session_loaded'] is False
    assert empty['calls'][0]['scores']==[] and empty['calls'][0]['details']['inference_ms']==0
    assert 'pad_id' not in empty['calls'][0]['details']
    assert ordered['calls'][0]['scores']==[29.,30.,28.,31.]
    assert ordered['calls'][0]['details']['pair_tokens']==[5,7,5,6]
    assert ordered['calls'][0]['details']['pad_id']==7
    assert truncated['calls'][0]['scores']==[535.]
    assert truncated['calls'][0]['details']['truncated_documents']==1
    assert all(item['original_rejected'] for item in fixtures['invalid'].values())
    assert json.loads((tmp_path/'original.json').read_text())==result


def test_original_batch_padding_and_character_guard_are_independent(original,tmp_path):
    from tools.rust_migration.ettin_fixtures import generate
    from tools.rust_migration.ettin_reference import capture
    reference=original
    pair=generate(reference,tmp_path/'fixtures')['pair']
    cases=[{'id':'batch','options':{'batch_size':3},'calls':[
        {'op':'tokens','query':'x','texts':['y','x x x','x','y y']},
        {'op':'score','query':'x','texts':['y','x x x','x','y y']}]},
        {'id':'allowed-chars','options':{},'calls':[{'op':'score','query':'x'+' '*65535,'texts':['y']}]},
        {'id':'rejected-chars','options':{},'calls':[{'op':'score','query':'x'+' '*65536,'texts':['y']}]},
        {'id':'rejected-pool','options':{},'calls':[{'op':'score','query':'x','texts':['y']*11}]}]
    result=capture(reference,Path(pair['source']),tmp_path/'original.json',definition=pair['definition'],
                   prepared=Path(pair['prepared']),cases=cases)
    batch,allowed,rejected,pool=result['results']
    first=batch['calls'][0][0]
    assert first['ids']==[8,1,9,2,9,7,7]
    assert first['attention_mask']==[1,1,1,1,1,0,0]
    assert batch['calls'][1]['scores']==[29.,30.,28.,31.]
    assert batch['cpu_arena'] is True and batch['intra_threads']==4 and batch['inter_threads']==1
    assert allowed['calls'][0]['scores']==[29.]
    assert 'too long' in rejected['calls'][0]['error']['message']
    assert 'top10' in pool['calls'][0]['error']['message'] and pool['session_loaded'] is False


def test_fixture_generation_resolves_relative_output_and_rejects_source_drift(original,tmp_path,monkeypatch):
    import pytest
    from tools.rust_migration.ettin_fixtures import generate
    from tools.rust_migration.ettin_reference import source_state
    reference=original
    monkeypatch.chdir(tmp_path)
    fixtures=generate(reference,Path('relative'))
    assert not (tmp_path/'fixture-environment').exists(), 'validation HOME must not become vendored fixture data'
    pair=fixtures['pair'];source=Path(pair['source'])
    assert source.is_absolute() and source_state(source,pair['definition']['source'])
    (source/'config.json').write_text('corrupt')
    with pytest.raises(ValueError,match='artifact'):
        source_state(source,pair['definition']['source'])
    assert str(tmp_path) not in (tmp_path/'relative/manifest.json').read_text()
