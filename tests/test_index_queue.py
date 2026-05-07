"""IndexQueue: dedup-by-path batch logic + lifecycle."""

from __future__ import annotations

import time

from ken.daemon.index_queue import IndexQueue, _Event


def test_drain_batch_dedupes_last_writer_wins(tmp_path):
    """Two events for the same path within the debounce window collapse."""
    (tmp_path / ".ken").mkdir()
    q = IndexQueue(tmp_path)
    head = _Event(action="reindex", rel="src/a.py")
    # Pre-load follow-ups so _drain_batch will pick them up.
    q._queue.put(_Event(action="reindex", rel="src/a.py"))
    q._queue.put(_Event(action="delete", rel="src/a.py"))
    batch = q._drain_batch(head)
    # Last action wins.
    assert batch == {"src/a.py": "delete"}


def test_drain_batch_respects_max_size(tmp_path):
    from ken.daemon.index_queue import BATCH_MAX_SIZE

    (tmp_path / ".ken").mkdir()
    q = IndexQueue(tmp_path)
    head = _Event(action="reindex", rel="head")
    # Push more than BATCH_MAX_SIZE follow-ups to confirm we cap.
    for i in range(BATCH_MAX_SIZE + 50):
        q._queue.put(_Event(action="reindex", rel=f"f{i}.py"))
    batch = q._drain_batch(head)
    assert len(batch) <= BATCH_MAX_SIZE


def test_drain_batch_stop_sentinel_breaks(tmp_path):
    """A None in the queue mid-drain stops collection without crashing."""
    (tmp_path / ".ken").mkdir()
    q = IndexQueue(tmp_path)
    head = _Event(action="reindex", rel="a.py")
    q._queue.put(_Event(action="reindex", rel="b.py"))
    q._queue.put(None)
    q._queue.put(_Event(action="reindex", rel="never-seen.py"))  # past sentinel
    batch = q._drain_batch(head)
    assert "a.py" in batch
    assert "b.py" in batch
    assert "never-seen.py" not in batch


def test_queue_lifecycle_start_stop(tmp_path):
    """start() launches a thread; stop() joins it cleanly."""
    (tmp_path / ".ken").mkdir()
    q = IndexQueue(tmp_path)
    q.start()
    assert q._thread is not None and q._thread.is_alive()
    q.stop(timeout=2.0)
    assert q._thread is None


def test_queue_drains_a_real_event_via_worker(tmp_path):
    """End-to-end: push a delete for a non-existent file → it's a no-op
    but proves the worker thread is consuming events."""
    (tmp_path / ".ken").mkdir()
    # Pre-create the DB with schema so the worker's connection can find ci_files.
    from ken.db import connect, init_schema
    db_conn = connect(tmp_path / ".ken" / "ken.db")
    init_schema(db_conn)
    db_conn.close()

    batches = []
    q = IndexQueue(tmp_path, on_batch=lambda stats, deleted: batches.append((stats, deleted)))
    q.start()
    try:
        q.delete("ghost.py")
        # Worker should pick it up within BATCH_DRAIN_S.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not batches:
            time.sleep(0.05)
    finally:
        q.stop(timeout=2.0)
    assert batches  # at least one batch processed
