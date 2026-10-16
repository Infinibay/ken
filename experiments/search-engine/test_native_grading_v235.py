import hashlib
import json

import pytest
from native_grading_v235 import validate_result, score_slots, verify_capture


def test_source_faithfulness_is_checked_before_any_fragment_credit(tmp_path):
    source=tmp_path/'code.py'; source.write_bytes(b'first\r\nsecond\r\nthird\r\n')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    pins={'code.py':digest}
    result={'path':'code.py','source_hash':digest,'stale':False,
            'entity_span':{'start_line':1,'end_line':3},
            'evidence':[{'start_line':2,'end_line':3,'content':'second\nthird'}]}
    assert validate_result(result,tmp_path,pins)
    result['evidence'][0]['content']='forged text'
    with pytest.raises(ValueError):
        validate_result(result,tmp_path,pins)


def test_errors_remain_misses_and_correct_native_rank_is_preserved():
    match=lambda r,t:r==t
    assert score_slots([],['gold'],match)=={'hit1':0,'hit10':0,'first_relevant_rank':None}
    slots=['wrong','gold']
    assert score_slots(slots,['gold'],match)=={'hit1':0,'hit10':1,'first_relevant_rank':2}
    assert score_slots(['gold'],['gold'],match)['hit1']==1
    assert score_slots(['wrong']*10+['gold'],['gold'],match)['hit10']==0


def test_grading_refuses_unclosed_or_modified_capture(tmp_path):
    with pytest.raises(ValueError, match='closed'):
        verify_capture(tmp_path)
    response=tmp_path/'response.json'; response.write_text('[]')
    digest=hashlib.sha256(response.read_bytes()).hexdigest()
    (tmp_path/'closure.json').write_text(json.dumps({'all_outputs_closed':True,
        'response_pins':{'response.json':digest}}))
    assert verify_capture(tmp_path)['all_outputs_closed']
    response.write_text('["changed"]')
    with pytest.raises(ValueError,match='changed'):
        verify_capture(tmp_path)


def test_anchor_ranges_without_visible_content_cannot_be_credited(tmp_path):
    source=tmp_path/'code.py'; source.write_text('source line\n')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    result={'path':'code.py','source_hash':digest,'stale':False,
            'entity_span':{'start_line':1,'end_line':1},
            'evidence':[{'start_line':1,'end_line':1}]}
    with pytest.raises(ValueError,match='content'):
        validate_result(result,tmp_path,{'code.py':digest})


def test_capture_cannot_close_with_empty_manifest(tmp_path):
    (tmp_path/'closure.json').write_text(json.dumps({'all_outputs_closed':True,'response_pins':{}}))
    with pytest.raises(ValueError,match='empty'):
        verify_capture(tmp_path)


def test_every_consumed_result_path_must_be_pinned(tmp_path):
    first=tmp_path/'other.json'; first.write_text('[]')
    (tmp_path/'closure.json').write_text(json.dumps({'all_outputs_closed':True,
        'response_pins':{'other.json':hashlib.sha256(first.read_bytes()).hexdigest()}}))
    second=tmp_path/'symbols.json'; second.write_text('[]')
    with pytest.raises(ValueError,match='unpinned'):
        verify_capture(tmp_path,required_paths=['symbols.json'])
