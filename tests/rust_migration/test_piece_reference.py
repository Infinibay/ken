"""Source-piece observations stay bound to actual original inputs and discovery."""
import json,copy
from pathlib import Path
from tools.rust_migration.piece_reference import validate_reference,definitions
ROOT=Path(__file__).resolve().parents[2]
def test_catalog_observations_authenticate_complete_input_and_original_suite():
 value=json.loads((ROOT/'crates/ken-retrieval/tests/fixtures/piece-reference-catalog.json').read_bytes())
 assert len(value['cases'])==len(definitions('catalog'))==38
 assert not validate_reference(value,'catalog')
 for change in ['input','result','observer','skip']:
  v=copy.deepcopy(value)
  if change=='input':v['cases'].pop()
  elif change=='result':v['cases'][0]['result']={}
  elif change=='observer':v['script_sha256']='0'*64
  else:v['test_states'][0]['outcome']='skipped'
  assert validate_reference(v,'catalog')
