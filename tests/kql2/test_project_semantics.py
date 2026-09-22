import sqlite3

from ken.kql2.service import search

QUERY = '''language "kql/2"; module t;
query q { callable $a { name: "caller"; } callable $b { name: "target"; }
          where possible_call($a,$b); select $a.name,$b.name; }'''


def test_cross_file_link_is_persisted_and_invalidated_by_edit(tmp_path):
    (tmp_path/'lib.py').write_text('def target():\n return 1\n')
    path = tmp_path/'main.py'
    path.write_text('from lib import target\ndef caller():\n return target()\n')
    first = search(tmp_path,QUERY)
    assert first['rows'] == [['caller','target']]
    database = tmp_path/'.ken/structural/v2/store.sqlite'
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM k2_analysis').fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM k2_semantic_facts WHERE relation='CALLS'").fetchone()[0] == 1
    path.write_text('def caller():\n return 0\n')
    second = search(tmp_path,QUERY)
    assert second['rows'] == []
    assert second['unknown_candidates'] == 1
    assert second['analysis']['parsed_units'] == 1
    assert second['analysis']['result_cache'] == 'miss'


def test_unresolved_destination_does_not_become_negative_proof(tmp_path):
    (tmp_path/'a.py').write_text('def caller():\n return dynamic_target()\ndef target(): pass\n')
    result = search(tmp_path,QUERY.replace('where possible_call', 'where not possible_call'),cache_mb=0)
    assert result['rows'] == [] and result['unknown_candidates'] == 1


def test_plain_structural_query_does_not_materialize_semantics(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    search(tmp_path,'language "kql/2"; module t; query q { class $c {} select $c; }')
    with sqlite3.connect(tmp_path/'.ken/structural/v2/store.sqlite') as db:
        assert db.execute('SELECT count(*) FROM k2_analysis').fetchone()[0] == 0


def test_cached_and_ephemeral_semantic_results_agree(tmp_path):
    (tmp_path/'lib.py').write_text('def target(): pass')
    (tmp_path/'main.py').write_text('from lib import target\ndef caller():\n target()')
    assert search(tmp_path,QUERY)['rows'] == search(tmp_path,QUERY,cache_mb=0)['rows'] == [['caller','target']]
