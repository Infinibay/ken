"""A failed cleanup must not skip an independently owned resource."""

import sqlite3

import pytest

from ken.kql2 import graph_execution, local_hazards, request
from ken.kql2 import service as indexed_service
from ken.kql2.exploration import service as exploration_service
from ken.structural.index_service import project_index
from ken.structural_store import Store
from ken.structural_store.acquisition import AcquisitionLock
from ken.structural_store.graph_index import GraphIndex

QUERY = 'language "kql/2"; module t; query q { node $n {kind:"if";} select $n.line; }'


def test_project_index_closes_its_store_when_index_close_raises(tmp_path, monkeypatch):
    """A real warm index keeps the store reachable after an injected failure."""
    (tmp_path / "a.py").write_text("class A: pass\n")
    with project_index(tmp_path):
        pass

    def fail_close(self):
        """Model an index cleanup callback that fails before closing the store."""
        raise RuntimeError("injected index cleanup failure")

    monkeypatch.setattr(GraphIndex, "close", fail_close)
    retained = None
    with (
        pytest.raises(RuntimeError, match="injected index cleanup failure"),
        project_index(tmp_path) as (index, _analysis),
    ):
        retained = index.store
    assert retained is not None
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        retained.db.execute("SELECT 1")


def test_execute_graph_closes_index_when_engine_close_raises(monkeypatch):
    """The first cleanup exception must not skip the second close."""

    class FakeGraphIndex:
        """Record whether the index cleanup was attempted."""

        def __init__(self):
            """Start with the index open."""
            self.closed = False

        def close(self):
            """Record an index close without needing a graph fixture."""
            self.closed = True

    class FakeExecutor:
        """Fail the first cleanup after a completed minimal execution."""

        def __init__(self, *_args, **_kwargs):
            """Accept the real executor's construction call."""

        def execute(self, _plan):
            """Reach the cleanup path after execution."""
            return {}

        def close(self):
            """Inject the failure whose effects are under test."""
            raise RuntimeError("injected executor cleanup failure")

    index = FakeGraphIndex()
    monkeypatch.setattr(graph_execution, "GraphIndex", FakeGraphIndex)
    monkeypatch.setattr(graph_execution, "Executor", FakeExecutor)
    monkeypatch.setattr(graph_execution, "graph_index", lambda *_args: (index, True))
    monkeypatch.setattr(graph_execution, "relational_plan", lambda *_args: object())
    monkeypatch.setattr(graph_execution, "renew", lambda *_args: None)
    monkeypatch.setattr(request, "phase", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(local_hazards, "supports", lambda *_args: False)
    with pytest.raises(RuntimeError, match="injected executor cleanup failure"):
        graph_execution.execute_graph(
            object(),
            object(),
            1,
            reference=False,
            timeout_ms=None,
            max_states=None,
            max_rows=10,
            cancelled=None,
        )
    assert index.closed


def test_owned_graph_index_closes_store_when_cache_cleanup_raises():
    """An owned store outlives a failing cache cleanup only until finalization."""

    class FailingCache:
        """Fail on the first cache cleanup step."""

        def cache_clear(self):
            """Raise before any ordinary GraphIndex cleanup completes."""
            raise RuntimeError("injected cache cleanup failure")

    class Store:
        """Record the owned store's close call."""

        def __init__(self):
            """Start with no close attempts."""
            self.closes = 0

        def close(self):
            """Count close attempts made by the index."""
            self.closes += 1

    index = object.__new__(GraphIndex)
    index.term = FailingCache()
    index.store = Store()
    index.owns_store = True
    with pytest.raises(RuntimeError, match="injected cache cleanup failure"):
        index.close()
    assert index.store.closes == 1
    assert index.owns_store is False


def test_indexed_search_closes_store_if_acquisition_cleanup_raises(
    tmp_path, monkeypatch
):
    """An early query failure plus a lock-close failure must still close Store."""
    from ken.structural_store import maintenance

    (tmp_path / "a.py").write_text("if True:\n pass\n")
    stores = []

    class CapturedStore(Store):
        """Record the store opened by the public indexed search."""

        def __init__(self, *args, **kwargs):
            """Capture the instance after normal initialization."""
            self.close_attempted = False
            super().__init__(*args, **kwargs)
            stores.append(self)

        def close(self):
            """Record that independent store cleanup was attempted."""
            self.close_attempted = True
            super().close()

    class FailingLock(AcquisitionLock):
        """Release the lock but raise during its first close."""

        def close(self):
            """Inject an operational cleanup failure after release."""
            super().close()
            raise RuntimeError("injected acquisition cleanup failure")

    def fail_trim(_store):
        """Reach finalization before the normal early lock release."""
        raise ValueError("injected preparation failure")

    monkeypatch.setattr(indexed_service, "Store", CapturedStore)
    monkeypatch.setattr(indexed_service, "AcquisitionLock", FailingLock)
    monkeypatch.setattr(maintenance, "trim", fail_trim)
    with pytest.raises(RuntimeError, match="injected acquisition cleanup failure"):
        indexed_service.search(tmp_path, QUERY, cache_mb=10)
    assert len(stores) == 1
    try:
        assert stores[0].close_attempted
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            stores[0].db.execute("SELECT 1")
    finally:
        stores[0].db.close()


def test_exploration_releases_reacquired_lock_if_cache_close_raises(
    tmp_path, monkeypatch
):
    """The post-query lock is independent of syntax-cache cleanup."""
    (tmp_path / "a.py").write_text("if True:\n pass\n")
    locks = []
    original_close = exploration_service.SyntaxCache.close

    class CapturedLock(AcquisitionLock):
        """Expose both the initial and post-query acquisition handles."""

        def __init__(self, *args, **kwargs):
            """Capture each real lock opened by exploration search."""
            super().__init__(*args, **kwargs)
            locks.append(self)

    def fail_cache_close(cache):
        """Close the cache, then fail before the final lock close."""
        original_close(cache)
        raise RuntimeError("injected syntax-cache cleanup failure")

    monkeypatch.setattr(exploration_service, "AcquisitionLock", CapturedLock)
    monkeypatch.setattr(exploration_service.SyntaxCache, "close", fail_cache_close)
    with pytest.raises(RuntimeError, match="injected syntax-cache cleanup failure"):
        exploration_service.search(tmp_path, QUERY, cache_mb=1)
    try:
        assert len(locks) == 2
        assert all(lock.handle is None for lock in locks)
    finally:
        for lock in locks:
            if lock.handle is not None:
                lock.close()
