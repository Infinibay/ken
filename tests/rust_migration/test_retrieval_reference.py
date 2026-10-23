"""Input inventories and captured original outcomes are independent of native code."""
from copy import deepcopy
from tools.rust_migration.retrieval_reference import definitions,validate_reference

def test_kernel_inputs_are_unique_and_contain_no_answers():
    import json
    cases=definitions();assert json.loads(json.dumps(cases))==cases
    assert len(cases)>200 and len({c['id']for c in cases})==len(cases)
    assert {c['kind']for c in cases}=={'request','spans','bm25f','postings','dense','fusion'}
    assert all(set(c)=={'id','kind','input'}for c in cases)

def test_incomplete_original_kernel_capture_rejects():
    assert validate_reference({'format':'ken-retrieval-kernel-reference/1','cases':[]})
