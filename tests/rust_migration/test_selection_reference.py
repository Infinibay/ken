"""Original text observations are independent from native interpretation."""
from tools.rust_migration.selection_reference import definitions,validate_reference

def test_text_inputs_preserve_query_authority_boundaries():
    cases=definitions('text')
    assert len(cases)>200 and len({c['id']for c in cases})==len(cases)
    assert all(set(c)=={'id','kind','input'}for c in cases)
    assert {'intent','locator','module','identifier'}=={c['kind']for c in cases}
    assert any('\ud800'in c['input'].get('query','')for c in cases)
    assert any('::'in c['input'].get('query','')for c in cases)

def test_incomplete_original_text_capture_rejects():
    assert validate_reference({'family':'text','cases':[]},'text')
