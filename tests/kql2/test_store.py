import sqlite3
from pathlib import Path

import pytest

from ken.structural.model import Entity, Fact, IR
from ken.structural_store import Store, StoreFormatError
from ken.structural_store.migrations import migrate
from ken.structural_store.schema import APPLICATION_ID, VERSION
from ken.structural_store.store import scalar


def unit(path='a.py', name='A'):
    ir = IR(path,'python')
    ir.entities['c'] = Entity('c','CLASS',name,path,1,2,{'flag': True, 'count': 1})
    ir.facts = [Fact('c','EDGE','c',{'guard':g},[g]) for g in ('left','right')]
    return ir


def test_up_down_up(tmp_path):
    path = tmp_path/'store.sqlite'
    with Store(path) as store:
        migrate(store.db)
        migrate(store.db,0)
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == 0
        migrate(store.db)
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == VERSION
        assert store.db.execute('PRAGMA foreign_keys').fetchone()[0] == 1


@pytest.mark.parametrize('mutation', [
    'PRAGMA user_version=99', 'PRAGMA application_id=0',
    "UPDATE k2_migrations SET checksum='wrong'", 'DROP INDEX k2_nodes_kind_name',
    'CREATE TABLE alien(x)',
])
def test_reject_modified_or_future_store(tmp_path, mutation):
    path = tmp_path/'store.sqlite'
    with Store(path) as store:
        store.db.execute(mutation)
    with pytest.raises(StoreFormatError):
        Store(path)


def test_foreign_db_is_untouched(tmp_path):
    path = tmp_path/'ken.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE cr_findings(content)')
        db.execute("INSERT INTO cr_findings VALUES ('important')")
    before = path.read_bytes()
    with pytest.raises(StoreFormatError):
        Store(path)
    assert before == path.read_bytes()


def test_rollback_failed_migration():
    db = sqlite3.connect('', isolation_level=None)
    # Authorizer injects a DDL failure after the first tables are created.
    db.set_authorizer(lambda op,a,b,c,d: sqlite3.SQLITE_DENY if op == sqlite3.SQLITE_CREATE_TABLE and a == 'k2_nodes' else sqlite3.SQLITE_OK)
    with pytest.raises(sqlite3.DatabaseError):
        migrate(db)
    db.set_authorizer(None)
    assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    assert db.execute('PRAGMA user_version').fetchone()[0] == 0
    db.close()


def test_roundtrip_and_contexts(tmp_path):
    with Store(tmp_path/'s.sqlite') as store:
        ir = unit()
        uid = store.put_unit('key',ir,'hash','frontend')
        assert store.put_unit('key',ir,'hash','frontend') == uid
        assert store.load_unit(uid).to_dict() == ir.to_dict()
        snapshot = store.publish([uid], expected_parent=None)
        nodes = list(store.scan(snapshot,kind='CLASS',name='A'))
        assert len(nodes) == 1
        assert store.properties(nodes[0])['flag'] is True
        assert store.properties(nodes[0])['count'] == 1
        assert len(store.db.execute('SELECT context FROM k2_facts').fetchall()) == 2
        assert scalar(True) != scalar(1) != scalar('1')


def test_snapshot_revision_add_delete_and_atomic_conflict(tmp_path):
    with Store(tmp_path/'s.sqlite') as store:
        a = store.put_unit('a',unit(),'h','v')
        first = store.publish([a],expected_parent=None)
        b = store.put_unit('b',unit(name='B'),'h2','v')
        with pytest.raises(ValueError,match='two revisions'):
            store.publish([a,b],expected_parent=first)
        assert store.current == first
        second = store.publish([b],expected_parent=first)
        assert [n.name for n in store.scan(first)] == ['A']
        assert [n.name for n in store.scan(second)] == ['B']
        with pytest.raises(ValueError,match='conflict'):
            store.publish([],expected_parent=first)
        empty = store.publish([],expected_parent=second)
        assert list(store.scan(empty)) == []
        with pytest.raises(KeyError):
            list(store.scan(99999))


def test_foreign_unit_publication_rolls_back(tmp_path):
    with Store(tmp_path/'s.sqlite') as store:
        with pytest.raises(KeyError):
            store.publish([12345],expected_parent=None)
        assert store.current is None


def test_cache_zero_does_not_create_path(tmp_path):
    path = tmp_path/'nonexistent'/'s.sqlite'
    with Store(path,cache_mb=0) as store:
        uid = store.put_unit('a',unit(),'h','v')
        assert uid
    assert not path.parent.exists()


def test_budget_rollback(tmp_path):
    with Store(tmp_path/'s.sqlite',cache_mb=1) as store:
        store.limit_bytes = store.allocated_bytes - 1
        with pytest.raises(MemoryError):
            store.put_unit('a',unit(),'h','v')
        assert store.find_unit('a') is None


@pytest.mark.parametrize('budget', [-1,float('nan'),float('inf')])
def test_bad_budget(budget):
    with pytest.raises(ValueError):
        Store(cache_mb=budget)


def test_reader_old_snapshot_survives_publication(tmp_path):
    path = tmp_path/'s.sqlite'
    with Store(path) as writer, Store(path) as reader:
        a = writer.put_unit('a',unit(),'h','v')
        snapshot = writer.publish([a],expected_parent=None)
        writer.publish([],expected_parent=snapshot)
        assert len(list(reader.scan(snapshot))) == 1
