import copy
import json
from pathlib import Path

import pytest

from ken.retrieval.public import render
from tests.retrieval.test_public_contracts import project


def response():
    return {'query':'locate operation','profile_version':'opaque-revision',
        'results':[{'path':'src/client.py','entity':{'qualname':'Client.redirect'},
            'source_hash':'a'*64,'ranking_score':.1234567,'stale':False,'truncated':True,
            'evidence':[{'start_line':12,'end_line':13,'content':'    prepare()\n    send()'},
                        {'start_line':42,'end_line':42,'content':'    return response'}]}],
        'warnings':[], 'truncated':True,'omitted_count':2}


def test_compact_text_preserves_disjoint_ranges_source_order_and_truncation():
    data = response(); before = copy.deepcopy(data)
    text = render(data)
    assert text == ('src/client.py:12-13 :: Client.redirect [partial]\n'
                    '    prepare()\n    send()\n'
                    '@42-42\n    return response\n\n'
                    '2 more results omitted.')
    assert data == before
    assert 'ranking_score' not in text and 'opaque-revision' not in text and 'a'*64 not in text
    assert len(text) < len(json.dumps(data,separators=(',',':')))


def test_compact_empty_error_and_stale_responses_remain_actionable():
    assert render({'results':[], 'warnings':[]}) == 'No matches.'
    assert render({'ok':False,'error':'Index is missing.', 'next_action':'Run ken retrieval index.'}) == 'Index is missing.\nRun ken retrieval index.'
    data = response(); data['results'][0].update(stale=True,evidence=[])
    data['warnings'] = ['Source changed; reindex before quoting.']
    text = render(data)
    assert 'Client.redirect [stale]' in text
    assert 'Source changed; reindex before quoting.' in text
    assert 'prepare()' not in text


def test_compact_cli_and_mcp_share_text_while_evidence_keeps_structure(tmp_path,monkeypatch,capsys):
    from ken.cli import main
    from ken.mcp import server
    project(tmp_path,monkeypatch)
    monkeypatch.setattr(server,'_PROJECT_ROOT',tmp_path)
    query = 'Where is `redirect` defined?'
    structured = server.ken_find(query,scope='symbols',response_format='evidence')
    compact = server.ken_find(query,scope='symbols',response_format='compact')
    assert isinstance(structured,dict) and isinstance(compact,str)
    assert compact == render(structured)
    assert main(['search-symbols',query,'--path',str(tmp_path),'--response-format','compact']) == 0
    assert capsys.readouterr().out == compact+'\n'
    assert 'client.py:' in compact and "headers.pop('Authorization', None)" in compact


def test_compact_text_does_not_silently_become_quoted_json(tmp_path,monkeypatch,capsys):
    from ken.cli import main
    project(tmp_path,monkeypatch)
    assert main(['search-files','redirect','--path',str(tmp_path),'--response-format','compact','--json']) == 1
    captured=capsys.readouterr()
    assert not captured.out
    assert '--response-format evidence --json' in captured.err


def test_compact_scope_validation_keeps_existing_search_boundaries(tmp_path,monkeypatch):
    from ken.mcp import server
    project(tmp_path,monkeypatch)
    monkeypatch.setattr(server,'_PROJECT_ROOT',tmp_path)
    with pytest.raises(ValueError,match='files or symbols'):
        server.ken_find('operation',scope='text',response_format='compact')


def test_persistent_mcp_serves_compact_as_plain_text(tmp_path,monkeypatch):
    import asyncio
    import sys
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from ken.db import connect
    from ken import _paths
    from ken.retrieval.public import find
    project(tmp_path,monkeypatch)
    query='Where is `redirect` defined?'
    with connect(_paths.db_path(tmp_path)) as conn:
        expected=render(find(conn,tmp_path,query))
    async def exercise():
        params=StdioServerParameters(command=sys.executable,args=['-m','ken','mcp',str(tmp_path)],
                                     env={'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')})
        with (tmp_path/'mcp-compact-stderr.log').open('w') as errlog:
            async with stdio_client(params,errlog=errlog) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    for _ in range(2):
                        result=await session.call_tool('ken_find',{'query':query,'scope':'symbols',
                            'response_format':'compact'},read_timeout_seconds=10)
                        assert not result.is_error
                        assert len(result.content)==1 and result.content[0].type=='text'
                        assert result.content[0].text==expected
    asyncio.run(exercise())


def test_tools_passthrough_honors_explicit_compact_response(tmp_path,monkeypatch,capsys):
    from ken.cli import main
    from ken.mcp import server
    project(tmp_path,monkeypatch)
    monkeypatch.setattr(server,'_PROJECT_ROOT',tmp_path)
    query='Where is `redirect` defined?'
    expected=server.ken_find(query,scope='symbols',response_format='compact')
    assert main(['tools','--path',str(tmp_path),'find',query,'--scope','symbols',
                 '--response-format','compact']) == 0
    assert capsys.readouterr().out == expected+'\n'
