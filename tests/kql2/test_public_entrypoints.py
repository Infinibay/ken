import json

from ken.cli import main
from ken.kql2.service import search

QUERY = 'language "kql/2"; module t; query q { class $c {} select $c.name; }'


def test_public_cli_and_python_api_agree(tmp_path, capsys):
    (tmp_path/'a.py').write_text('class A: pass')
    file = tmp_path/'q.kql'; file.write_text(QUERY)
    assert main(['kql2',str(file),'--root',str(tmp_path),'--cache-mb','0']) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli['rows'] == search(tmp_path, QUERY, cache_mb=0)['rows'] == [['A']]


def test_cli_library_and_resource_exit_status(tmp_path, capsys):
    (tmp_path/'a.py').write_text('class A: pass')
    library = tmp_path/'lib.kql'
    library.write_text('language "kql/2"; module lib; predicate P(TypeDecl $c) { true }')
    query = tmp_path/'q.kql'
    query.write_text(QUERY.replace('module t;', 'module t; import lib;').replace('select $c.name;', 'where lib.P($c); select $c.name;'))
    assert main(['kql2',str(query),'--root',str(tmp_path),'--library',str(library),'--cache-mb','0','--max-states','1']) == 3
    assert not json.loads(capsys.readouterr().out)['complete']


def test_mcp_and_api_agree(tmp_path, monkeypatch):
    from ken.mcp import server
    monkeypatch.setattr(server, '_PROJECT_ROOT', tmp_path)
    (tmp_path/'a.py').write_text('class A: pass')
    result = server.ken_find(query=QUERY,scope='structure',query_language='kql/2',cache_mb=0)
    assert result['rows'] == search(tmp_path, QUERY, cache_mb=0)['rows'] == [['A']]
