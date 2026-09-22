"""Committed acquisition batches stay invisible until the READY transition."""

import sqlite3

import pytest

from ken.structural.model import IR, Fact
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish
from ken.structural_store.migrations import migrate
from tests.kql2.test_graph_columns import stored


def test_publication_waits_for_index_migration_without_replaying_input(tmp_path):
    path = tmp_path / "index.sqlite"
    with Store(path) as writer:
        migrate(writer.db, 12)
        snapshot = writer.publish([], expected_parent=None)
        writer.db.execute("PRAGMA busy_timeout=1")
        with sqlite3.connect(path, isolation_level=None) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            released = []

            def check():
                if blocker.in_transaction:
                    blocker.execute("COMMIT")
                    migrate(blocker)
                    released.append(True)

            ir = IR("a", "python", view="query", facts=[Fact("once", "R", "value")])
            graph = publish(writer, snapshot, "test", ir, check=check, consume=True)
        assert released == [True]
        assert not ir.facts
        assert [fact.subject for fact in GraphIndex(writer, graph).rows("R")] == [
            "once"
        ]


def test_busy_retry_honors_cancellation_before_consuming_input(tmp_path):
    path = tmp_path / "index.sqlite"
    with Store(path) as writer:
        snapshot = writer.publish([], expected_parent=None)
        writer.db.execute("PRAGMA busy_timeout=1")
        with sqlite3.connect(path, isolation_level=None) as blocker:
            blocker.execute("BEGIN IMMEDIATE")

            def cancel():
                raise RuntimeError("cancel while waiting")

            ir = IR("a", "python", view="query", facts=[Fact("kept", "R", "value")])
            with pytest.raises(RuntimeError, match="cancel while waiting"):
                publish(writer, snapshot, "test", ir, check=cancel, consume=True)
            assert len(ir.facts) == 1
            blocker.execute("ROLLBACK")


def test_partial_batches_are_hidden_and_failure_preserves_previous_graph(tmp_path):
    path = tmp_path / "s.sqlite"
    with Store(path) as writer, Store(path) as reader:
        old = stored(
            writer,
            IR("a", "python", view="query", facts=[Fact("old", "R", "value")]),
            "old",
        )
        old_reader = GraphIndex(reader, old.graph)
        snapshot = writer.publish([], expected_parent=writer.current, profile="new")
        ir = IR(
            "a",
            "python",
            view="query",
            facts=[Fact(str(i), "R", "value") for i in range(33000)],
        )
        observations = []

        def check():
            row = reader.db.execute(
                "SELECT graph_id FROM k2_graphs WHERE fingerprint='new'"
            ).fetchone()
            if row is None:
                return
            with pytest.raises(KeyError):
                GraphIndex(reader, row[0])
            count = reader.db.execute(
                "SELECT count(*) FROM k2_graph_facts WHERE graph_id=?", row
            ).fetchone()[0]
            if count:
                observations.append(count)
                assert next(iter(old_reader.rows("R"))).subject == "old"
                raise RuntimeError("cancel after committed batch")

        with pytest.raises(RuntimeError, match="committed batch"):
            publish(writer, snapshot, "new", ir, check=check)
        assert observations == [32768]
        assert (
            reader.db.execute(
                "SELECT 1 FROM k2_graphs WHERE fingerprint='new'"
            ).fetchone()
            is None
        )
        assert len(old_reader.rows("R")) == 1
        graph = publish(writer, snapshot, "new", ir)
        assert len(GraphIndex(reader, graph).rows("R")) == 33000


def test_abandoned_publication_is_replaced_but_live_writer_is_protected(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        ir = IR("a", "python", view="query")
        snapshot = store.publish([], expected_parent=None)
        graph = publish(store, snapshot, "key", ir)
        store.db.execute(
            "UPDATE k2_graph_publications SET ready=0,lease_id=? WHERE graph_id=?",
            (store.lease_id, graph),
        )
        with pytest.raises(RuntimeError, match="in progress"):
            publish(store, snapshot, "key", ir)
        store.db.execute(
            "UPDATE k2_graph_publications SET lease_id='expired' WHERE graph_id=?",
            (graph,),
        )
        rebuilt = publish(store, snapshot, "key", ir)
        assert len(GraphIndex(store, rebuilt).ir.facts) == 0


def test_private_acquisition_buffers_can_be_consumed_without_changing_stored_graph():
    from ken.structural.frontend import lower_source
    from ken.structural.query_view import query_graph
    from ken.structural.semantic import link_project

    ir = query_graph(
        link_project([lower_source("def f(x):\n return x\n", "python", "a.py")])
    ).ir
    expected = ir.to_dict()
    with Store(cache_mb=0) as store:
        snapshot = store.publish([], expected_parent=None)
        graph = publish(store, snapshot, "owned", ir, consume=True)
        assert not ir.entities and not ir.operations and not ir.facts
        stored_ir = GraphIndex(store, graph).ir
        from dataclasses import asdict

        assert [asdict(entity) for entity in stored_ir.entities.values()] == list(
            expected["entities"].values()
        )
        assert [asdict(op) for op in stored_ir.operations] == expected["operations"]
        assert [asdict(fact) for fact in stored_ir.facts] == expected["facts"]


def test_fresh_normalization_replaces_abandoned_rows_instead_of_reusing_ordinals(
    tmp_path,
):
    with Store(tmp_path / "s.sqlite") as store:
        original = IR("a", "python", view="query", facts=[Fact("a", "R", "b")])
        snapshot = store.publish([], expected_parent=None)
        graph = publish(store, snapshot, "same-source", original)
        store.db.execute(
            "UPDATE k2_graph_publications SET ready=0,lease_id='expired' WHERE graph_id=?",
            (graph,),
        )
        reordered = IR("a", "python", view="query", facts=[Fact("b", "R", "a")])
        replacement = publish(store, snapshot, "same-source", reordered)
        index = GraphIndex(store, replacement)
        assert [(f.subject, f.object) for f in index.rows("R")] == [("b", "a")]


def test_abandoned_committed_prefix_resumes_without_duplicate_records(
    tmp_path, monkeypatch
):
    from ken.structural_store.graph_publication import Publication

    with Store(tmp_path / "s.sqlite") as store:
        ir = IR(
            "a",
            "python",
            view="query",
            facts=[Fact(str(i), "R", "value", {"i": i}) for i in range(33000)],
        )
        snapshot = store.publish([], expected_parent=None)

        def interrupt():
            if (
                store.db.execute("SELECT count(*) FROM k2_graph_facts").fetchone()[0]
                >= 32768
            ):
                raise RuntimeError("process stopped")

        with monkeypatch.context() as patch:
            patch.setattr(Publication, "discard", lambda _: None)
            with pytest.raises(RuntimeError, match="stopped"):
                publish(store, snapshot, "resume", ir, check=interrupt)
        (graph,) = store.db.execute("SELECT graph_id FROM k2_graphs").fetchone()
        assert (
            store.db.execute("SELECT count(*) FROM k2_graph_facts").fetchone()[0]
            == 32768
        )
        store.db.execute("UPDATE k2_graph_publications SET lease_id='expired'")
        assert (
            publish(store, snapshot, "resume", ir, consume=True, resume=True) == graph
        )
        index = GraphIndex(store, graph)
        assert len(index.ir.facts) == 33000
        assert [f.attrs["i"] for f in index.rows("R", "32999")] == [32999]
        assert len(index.rows("R", "0")) == 1


def test_publication_recovers_expired_lease_only_while_it_still_owns_graph(tmp_path):
    with Store(tmp_path / "s.sqlite") as store:
        ir = IR("a", "python", view="query", facts=[Fact("a", "R", "b")])
        snapshot = store.publish([], expected_parent=None)
        expired = False

        def pause(table, count):
            nonlocal expired
            if not expired:
                store.db.execute(
                    "DELETE FROM k2_leases WHERE lease_id=?", (store.lease_id,)
                )
                store.lease_renew_at = 0
                expired = True

        graph = publish(store, snapshot, "paused", ir, progress=pause)
        assert expired and len(GraphIndex(store, graph).rows("R")) == 1


def test_stale_publisher_cannot_write_or_discard_reclaimed_graph(tmp_path):
    from ken.structural_store.leases import SnapshotExpired

    with Store(tmp_path / "s.sqlite") as store:
        ir = IR("a", "python", view="query", facts=[Fact("a", "R", "b")])
        snapshot = store.publish([], expected_parent=None)

        def reclaimed(table, count):
            store.db.execute("UPDATE k2_graph_publications SET lease_id='replacement'")

        with pytest.raises(SnapshotExpired, match="ownership changed"):
            publish(store, snapshot, "reclaimed", ir, progress=reclaimed)
        assert store.db.execute(
            "SELECT ready,lease_id FROM k2_graph_publications"
        ).fetchall() == [(0, "replacement")]
        assert (
            store.db.execute("SELECT count(*) FROM k2_graph_facts").fetchone()[0] == 0
        )
