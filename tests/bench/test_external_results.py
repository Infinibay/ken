from pathlib import Path

from ken.parsers.python import parse_python_file
from ken.retrieval.passages import extract_passages


def source(tmp_path):
    text='def first():\n    prepare()\n    finish()\n\ndef second():\n    return 2\n'
    (tmp_path/'code.py').write_text(text)
    return extract_passages(text.encode(),parse_python_file(text.encode(),'code.py'),path='code.py')


def test_external_adapter_resolves_owner_from_visible_source_without_answer_labels(tmp_path):
    from ken.bench.external_results import OwnerLookup, normalize
    owners=OwnerLookup(source(tmp_path))
    raw={'query':'operation','results':[{'file_path':'code.py','start_line':2,'end_line':4,
        'content':'prepare()\n    finish()','score':.5}]}
    result=normalize(raw,tmp_path,owners)['results'][0]
    assert result['entity']['qualname']=='first'
    assert result['evidence']==[{'start_line':2,'end_line':3,'content':'    prepare()\n    finish()'}]
    # A chunk spanning two owners must not silently pick the correct answer.
    raw['results'][0].update(start_line=3,end_line=6,content='    finish()\n\ndef second():\n    return 2')
    assert normalize(raw,tmp_path,owners)['results'][0]['entity'] is None


def test_external_adapter_does_not_complete_a_partial_source_statement(tmp_path):
    from ken.bench.external_results import OwnerLookup, normalize
    owners=OwnerLookup(source(tmp_path))
    raw={'query':'operation','results':[{'file_path':'code.py','start_line':2,'end_line':3,
        'content':'    prepare()\n    fin','score':.5}]}
    result=normalize(raw,tmp_path,owners)['results'][0]
    assert result['evidence']==[{'start_line':2,'end_line':2,'content':'    prepare()'}]
    raw['results'][0]['content']='wrong source\n    finish()'
    assert normalize(raw,tmp_path,owners)['results'][0]['stale']


def test_external_adapter_keeps_first_result_and_enforces_line_and_json_budgets(tmp_path):
    import json
    from ken.bench.external_results import OwnerLookup, normalize
    text='def first():\n'+''.join(f'    value_{i} = {i}\n' for i in range(80))
    (tmp_path/'code.py').write_text(text)
    owners=OwnerLookup(extract_passages(text.encode(),parse_python_file(text.encode(),'code.py'),path='code.py'))
    native={'query':'operation','results':[{'file_path':'code.py','start_line':1,'end_line':81,
        'content':text,'score':float(100-i)} for i in range(10)]}
    response=normalize(native,tmp_path,owners,max_chars=1200)
    assert response['results'][0]['ranking_score']==100
    fragment=response['results'][0]['evidence'][0]
    assert fragment['end_line']-fragment['start_line']+1<=40
    assert fragment['content']=='\n'.join(text.splitlines()[fragment['start_line']-1:fragment['end_line']])
    assert len(json.dumps(response,ensure_ascii=False,separators=(',',':'))) <=1200


def test_external_byte_chunk_can_start_midline_without_losing_following_complete_lines(tmp_path):
    from ken.bench.external_results import OwnerLookup, normalize
    owners=OwnerLookup(source(tmp_path))
    raw={'query':'operation','results':[{'file_path':'code.py','start_line':1,'end_line':3,
        'content':':\n    prepare()\n    finish()','score':.5}]}
    result=normalize(raw,tmp_path,owners)['results'][0]
    assert not result['stale']
    assert result['entity']['qualname']=='first'
    assert result['evidence']==[{'start_line':2,'end_line':3,'content':'    prepare()\n    finish()'}]
    # The omitted declaration prefix is not manufactured as visible evidence.
    assert 'def first' not in result['evidence'][0]['content']


def test_external_chunk_extent_does_not_claim_unshown_native_suffix(tmp_path):
    from ken.bench.external_results import OwnerLookup, normalize
    owners=OwnerLookup(source(tmp_path))
    raw={'query':'operation','results':[{'file_path':'code.py','start_line':2,'end_line':3,
        'content':'    prepare()','score':.5}]}
    assert normalize(raw,tmp_path,owners)['results'][0]['truncated']
