"""Source-piece observations stay bound to actual original inputs and discovery."""
import json,copy,gzip
import pytest
from pathlib import Path
from tools.rust_migration.piece_reference import validate_reference,definitions
ROOT=Path(__file__).resolve().parents[2]
@pytest.mark.parametrize('family,count',[('catalog',38),('assembly',45),('ranking',84),('ranking-edges',13),('ranking-empty-declaration',1),('cards',60),('evidence',86)])
def test_catalog_observations_authenticate_complete_input_and_original_suite(family,count):
 suffix='-linux' if family in ('ranking-edges','ranking-empty-declaration') else ''
 if family in ('cards','evidence'):suffix='-linux-x86_64'
 path=ROOT/f'crates/ken-retrieval/tests/fixtures/piece-reference-{family}{suffix}.json'
 raw=path.read_bytes() if path.exists() else gzip.decompress(path.with_suffix('.json.gz').read_bytes())
 value=json.loads(raw)
 assert len(value['cases'])==len(definitions(family))==count
 assert not validate_reference(value,family)
 for change in ['input','result','observer','skip']:
  v=copy.deepcopy(value)
  if change=='input':v['cases'].pop()
  elif change=='result':v['cases'][0]['result']={}
  elif change=='observer':v['script_sha256']='0'*64
  else:v['test_states'][0]['outcome']='skipped'
  assert validate_reference(v,family)

def test_ranking_observers_are_shared_but_input_families_are_disjoint():
 from tools.rust_migration.piece_reference import SCRIPTS,SUITES
 assert SCRIPTS['ranking-edges']==SCRIPTS['ranking']
 assert SUITES['ranking-edges']==SUITES['ranking']
 assert not ({c['id'] for c in definitions('ranking')} & {c['id'] for c in definitions('ranking-edges')})
