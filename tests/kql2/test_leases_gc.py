import sqlite3
import subprocess
import sys
import json

from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.structural.model import IR, Entity
from ken.structural_store import Store
from ken.structural_store.leases import collect
from ken.structural_store.artifacts import write


def publish(store, key):
    ir = IR('a','python',entities={key:Entity(key,'CLASS',key,'a',1,1)})
    unit = store.put_unit(key,ir,key,'v')
    return store.publish([unit],expected_parent=store.current),unit


def test_active_reader_snapshot_is_pinned_during_gc(tmp_path):
    path = tmp_path/'s.db'
    with Store(path) as reader:
        old, old_unit = publish(reader,'A')
        with Store(path) as writer:
            publish(writer,'B')
            publish(writer,'C')
            result = collect(writer,retain=1)
            assert result['snapshots'] == 1
            assert list(reader.scan(old))[0].name == 'A'
    with Store(path) as cleaner:
        result = collect(cleaner,retain=1)
        assert result['snapshots'] == 1
        assert cleaner.find_unit('A') is None


def test_collection_defers_while_another_process_captures_units(tmp_path):
    path = tmp_path/'s.db'
    with Store(path) as first, Store(path) as second:
        first.put_unit('u',IR('a','python'),'h','v')
        assert collect(second)['deferred'] is True


def test_orphan_artifacts_cascade_and_units_are_reclaimed(tmp_path):
    path = tmp_path/'s.db'
    with Store(path) as store:
        old,_ = publish(store,'A')
        assert write(store,'r','result','v',b'data',snapshot=old)
    with Store(path) as store:
        publish(store,'B')
    with Store(path) as store:
        result = collect(store,retain=1)
        assert result['snapshots'] == result['units'] == 1
        assert store.db.execute("SELECT 1 FROM k2_artifacts WHERE artifact_key='r'").fetchone() is None


def test_expired_query_never_returns_a_successful_negative(tmp_path):
    with Store(tmp_path/'s.db') as store:
        snapshot,_ = publish(store,'A')
        store.db.execute('UPDATE k2_leases SET expires_ns=0')
        store.lease_renew_at = 0
        p = compile(parse('language "kql/2"; module t; query q { class $c {} select $c; }'))
        result = execute(p,store,snapshot)
        assert not result.complete and result.reason == 'snapshot_expired'


def test_crashed_process_lease_can_be_collected_after_expiry(tmp_path):
    path = tmp_path/'s.db'
    with Store(path) as store:
        old,_ = publish(store,'A')
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO k2_leases VALUES (?,?,?)',('crashed',old,0))
    with Store(path) as store:
        publish(store,'B')
        assert collect(store,retain=1)['snapshots'] == 1
        assert store.db.execute("SELECT 1 FROM k2_leases WHERE lease_id='crashed'").fetchone() is None


def test_two_processes_share_graph_acquisition(tmp_path):
    (tmp_path/'a.py').write_text('class A: pass')
    script = '''import json,sys
from pathlib import Path
from ken.kql2.service import search
print(json.dumps(search(Path(sys.argv[1]),'language "kql/2"; module t; query q { class $c {} select $c.name; }')))
'''
    processes = [subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        results.append(json.loads(out))
    assert all(r['rows'] == [['A']] for r in results)
    assert sorted(r['analysis']['parsed_units'] for r in results) == [0,1]
    assert results[0]['analysis']['snapshot'] == results[1]['analysis']['snapshot']
