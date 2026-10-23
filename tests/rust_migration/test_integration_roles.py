"""Recipes use literal original inputs; expected outputs never enter the native request."""
from pathlib import Path
from tools.rust_migration.integration_roles import role_cases


def test_each_nontransformer_role_has_an_independent_registered_original_case():
    repo=Path(__file__).resolve().parents[2]
    cases=role_cases(repo,'macos')
    assert {row['name']for row in cases}=={'static','potion','context','reranker','expansion','fastembed'}
    for row in cases:
        assert row['reference'].is_file()
        assert row['calls'] and row['expected']
        assert all('expected'not in call for call in row['calls'])
        assert all(call['id']for call in row['calls'])
    assert next(r for r in cases if r['name']=='potion')['expected']['vectors']
