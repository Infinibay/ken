from dataclasses import replace
from hashlib import sha256
import json
import sqlite3
import subprocess
import sys

import pytest

from ken.kql2.codec import decode,encode
from ken.kql2.compilation import clear_compilation_cache,compile_query,artifact_key
from ken.kql2.service import search
from ken.structural_store import Store
from ken.structural_store.artifacts import read,write
from ken.structural_store.migrations import migrate
from ken.structural_store.schema import BASE_STATEMENTS,CHECKSUMS,APPLICATION_ID,VERSION

QUERY='language "kql/2"; module t; query q { class $c {} select $c.name; }'


@pytest.fixture(autouse=True)
def clear():
    clear_compilation_cache()
    yield
    clear_compilation_cache()


def test_roundtrip_prepared_program(tmp_path):
    prepared,_,_=compile_query(tmp_path,QUERY,None,budget_bytes=1_000_000)
    payload=encode(prepared)
    assert decode(payload,max_bytes=len(payload))==prepared
    with pytest.raises(ValueError):
        decode(payload,max_bytes=1)


@pytest.mark.parametrize('mutate',[
    lambda value: value.update(tag='os.system'),
    lambda value: value['fields'].update(program='not a program'),
    lambda value: value['fields'].update(extra=1),
])
def test_closed_codec_rejects_unknown_types_and_fields(tmp_path,mutate):
    prepared,_,_=compile_query(tmp_path,QUERY,None,budget_bytes=1_000_000)
    value=json.loads(encode(prepared)); mutate(value)
    with pytest.raises(ValueError):
        decode(json.dumps(value).encode(),max_bytes=1_000_000)


def test_new_process_recovers_compilation_and_result(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    first=search(tmp_path,QUERY)
    script='''import json,sys
from pathlib import Path
from ken.kql2.service import search
print(json.dumps(search(Path(sys.argv[1]),sys.argv[2])))
'''
    process=subprocess.run([sys.executable,'-c',script,str(tmp_path),QUERY],capture_output=True,text=True,check=True)
    second=json.loads(process.stdout)
    assert second['rows']==first['rows']==[['A']]
    assert second['analysis']['compilation_cache']['status']=='disk_hit'
    assert second['analysis']['result_cache']=='disk_hit'
    assert second['analysis']['query_ms'] is None
    assert second['analysis']['parsed_units']==second['analysis']['scanned_nodes']==0


def test_edit_invalidates_result_but_not_program(tmp_path):
    path=tmp_path/'a.py'; path.write_text('class A: pass')
    search(tmp_path,QUERY)
    clear_compilation_cache()
    path.write_text('class B: pass')
    result=search(tmp_path,QUERY)
    assert result['rows']==[['B']]
    assert result['analysis']['compilation_cache']['status']=='disk_hit'
    assert result['analysis']['result_cache']=='miss'


def test_partial_outcome_not_saved_as_success(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    partial=search(tmp_path,QUERY,max_states=1)
    assert not partial['complete']
    full=search(tmp_path,QUERY)
    assert full['analysis']['result_cache']=='miss'
    assert full['rows']==[['A']]


def test_zero_ignores_existing_disk_artifacts(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    search(tmp_path,QUERY)
    result=search(tmp_path,QUERY,cache_mb=0)
    assert result['analysis']['compilation_cache']['status']=='disabled'
    assert result['analysis']['result_cache']=='miss'
    assert result['analysis']['parsed_units']==1


def test_corrupt_compilation_is_recomputed(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    search(tmp_path,QUERY)
    clear_compilation_cache()
    with sqlite3.connect(tmp_path/'.ken/structural/v2/store.sqlite') as db:
        db.execute("UPDATE k2_artifacts SET payload=x'7b7d' WHERE kind='compiled'")
    result=search(tmp_path,QUERY)
    assert result['analysis']['compilation_cache']['status']=='miss'
    assert result['rows']==[['A']]


def test_malformed_result_even_with_checksum_is_not_reused(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    search(tmp_path,QUERY)
    payload=json.dumps({'rows':[],'complete':True,'coverage_complete':True}).encode()
    with sqlite3.connect(tmp_path/'.ken/structural/v2/store.sqlite') as db:
        db.execute("UPDATE k2_artifacts SET payload=?,checksum=?,bytes=? WHERE kind='result'",(payload,sha256(payload).hexdigest(),len(payload)))
    result=search(tmp_path,QUERY)
    assert result['analysis']['result_cache']=='miss'
    assert result['rows']==[['A']]


def test_migration_v1_to_v2_and_back_preserves_graph(tmp_path):
    path=tmp_path/'store.sqlite'
    db=sqlite3.connect(path,isolation_level=None)
    for statement in BASE_STATEMENTS:
        db.execute(statement)
    db.execute(f'PRAGMA application_id={APPLICATION_ID}')
    db.execute('PRAGMA user_version=1')
    db.execute('INSERT INTO k2_migrations VALUES (1,?)',(CHECKSUMS[1],))
    db.execute("INSERT INTO k2_meta VALUES ('marker','keep')")
    db.close()
    with Store(path) as store:
        assert store.db.execute('PRAGMA user_version').fetchone()[0]==VERSION
        assert write(store,'a','plan','test',b'data')
        migrate(store.db,1)
        assert store.db.execute("SELECT value FROM k2_meta WHERE key='marker'").fetchone()[0]=='keep'
        migrate(store.db,2)
        assert read(store.db,'a','test',max_bytes=100) is None


def test_disk_artifact_eviction_and_oversized_rejection(tmp_path):
    with Store(tmp_path/'s.sqlite',cache_mb=1) as store:
        assert write(store,'a','test','v',b'a'*80000)
        assert write(store,'b','test','v',b'b'*80000)
        assert write(store,'c','test','v',b'c'*80000)
        assert read(store.db,'a','v',max_bytes=100000) is None
        assert read(store.db,'b','v',max_bytes=100000) is not None
        assert not write(store,'too_large','test','v',b'x'*210000)
        assert read(store.db,'b','v',max_bytes=100000) is not None


def test_read_only_cache_probe_during_uncommitted_initial_migration(tmp_path):
    from ken.structural_store.artifacts import read_existing
    database=tmp_path/'initializing.sqlite'
    writer=sqlite3.connect(database,isolation_level=None)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('BEGIN IMMEDIATE')
        writer.execute('CREATE TABLE not_committed_yet (value TEXT)')
        assert read_existing(database,'missing','codec',max_bytes=1000) is None
        writer.execute('ROLLBACK')
    finally:
        writer.close()


def test_read_only_cache_probe_does_not_accept_committed_foreign_schema(tmp_path):
    from ken.structural_store.artifacts import read_existing
    from ken.structural_store.migrations import StoreFormatError
    database=tmp_path/'foreign.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE foreign_data (value TEXT)')
    with pytest.raises(StoreFormatError):
        read_existing(database,'missing','codec',max_bytes=1000)
