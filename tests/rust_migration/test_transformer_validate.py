"""Incomplete platform/matrix receipts never establish acceptance."""
import json
from pathlib import Path
import pytest
from tools.rust_migration.transformer_validate import validate_transformer,aggregate_transformers

@pytest.mark.parametrize('case',['missing','empty','synthetic','no-profiles','wrong-platform','missing-core'])
def test_missing_or_partial_receipt_is_rejected(tmp_path,case):
 root=tmp_path/'receipt';root.mkdir();row={'scope':'transformer-local','format':'ken-transformer-acceptance/1','passed':True,'M2_accepted':False,'synthetic_fixture':False,'platform':'macos','architecture':'aarch64','profiles':[]}
 if case=='missing':pass
 elif case=='empty':(root/'summary.json').write_text('{}')
 else:
  if case=='synthetic':row['synthetic_fixture']=True
  if case=='wrong-platform':row['platform']='windows'
  (root/'summary.json').write_text(json.dumps(row))
 result=validate_transformer(root,Path(__file__).resolve().parents[2]);assert not result['passed'] and result['errors']

def test_matrix_requires_both_registered_platforms_and_exact33profiles(tmp_path):
 result=aggregate_transformers(tmp_path,Path(__file__).resolve().parents[2]);assert not result['passed'] and result['M2_accepted'] is False
