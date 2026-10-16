import asyncio,json,sys
from pathlib import Path
import pytest
from tests.retrieval.test_candidates import indexed
from ken.indexer import index_files
from ken.db import connect,init_schema


@pytest.fixture
def best_project(tmp_path):
    (tmp_path/'.ken').mkdir();(tmp_path/'.ken/meta.json').write_text('{}')
    (tmp_path/'reader.py').write_text('class Reader:\n    def read(self):\n        return 1\n')
    with connect(tmp_path/'.ken/ken.db') as conn:
        init_schema(conn);index_files(conn,tmp_path,[Path('reader.py')])
    return tmp_path


def test_default_cli_uses_primary_piece_and_json_opt_in(best_project,capsys):
    from ken.cli import main
    args=['search-symbols','Reader','--path',str(best_project)]
    assert main(args)==0
    text=capsys.readouterr().out
    assert 'Reader' in text and '1 | class Reader:' in text and not text.startswith('{')
    assert main([*args,'--json'])==0
    result=json.loads(capsys.readouterr().out)['results'][0]
    assert result['piece_kind']=='class' and result['entity']['qualname']=='Reader'
    assert main(['search-files','Reader','--path',str(best_project),'--piece-kind','class','--json'])==0
    assert json.loads(capsys.readouterr().out)['results'][0]['entity']['kind']=='class'


def test_real_stdio_mcp_defaults_to_same_primary_piece_and_forwards_kind(best_project):
    from ken.mcp import server
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters,stdio_client
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','ken','mcp',str(best_project)],env={'PYTHONPATH':str(Path(server.__file__).resolve().parents[2]),'PYTHONDONTWRITEBYTECODE':'1'})
        with (best_project/'mcp.log').open('w') as log:
            async with stdio_client(params,errlog=log) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    default=await session.call_tool('ken_find',{'query':'Reader','scope':'symbols'})
                    assert not default.is_error
                    text='\n'.join(c.text for c in default.content if c.type=='text')
                    assert '1 | class Reader:' in text and not text.startswith('{')
                    answer=await session.call_tool('ken_find',{'query':'Reader','scope':'files','piece_kind':'class','output_format':'json'})
                    assert not answer.is_error
                    result=json.loads('\n'.join(c.text for c in answer.content if c.type=='text'))['results'][0]
                    assert result['piece_kind']=='class' and result['entity']['qualname']=='Reader'
    asyncio.run(run())

def test_explicit_prepare_command_handles_empty_repository_without_models(tmp_path,capsys):
    from ken.cli import main
    assert main(['retrieval','prepare','--path',str(tmp_path),'--json'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['indexed_files']==0 and result['owners']==0
