from ken.kql2.service import search


def test_operation_domain_has_language_and_execution(tmp_path):
    (tmp_path/'a.py').write_text('def f():\n return 1\n return 2\n')
    query = '''language "kql/2"; module t; query q {
      operation $op { kind: "return"; language: "python"; execution: "unreachable"; }
      select $op.line;
    }'''
    assert search(tmp_path,query,cache_mb=0)['rows'] == [[3]]


def test_scoped_operation_domain_and_stable_id(tmp_path):
    (tmp_path/'a.py').write_text('def a(): return 1\ndef b(): return 2')
    query = '''language "kql/2"; module t; query q {
      callable $f { name: "a"; operation $op { kind: "return"; } }
      where owns($f,$op); select stable_id($op);
    }'''
    result = search(tmp_path,query,cache_mb=0)
    assert len(result['rows']) == 1 and 'return_statement' in result['rows'][0][0]


def test_unresolved_read_is_not_a_variable_declaration(tmp_path):
    (tmp_path/'a.py').write_text('def f():\n return missing\n')
    query = 'language "kql/2"; module t; query q { var $x {} select $x; }'
    assert search(tmp_path,query,cache_mb=0)['rows'] == []
