"""FileWatcher event handling."""

from __future__ import annotations

from watchfiles import Change

from ken.daemon.watcher import FileWatcher, MASS_CHANGE_THRESHOLD


class _Queue:
    def __init__(self) -> None:
        self.reindexed: list[str] = []
        self.deleted: list[str] = []
        self.resyncs = 0

    def reindex(self, rel: str) -> None:
        self.reindexed.append(rel)

    def delete(self, rel: str) -> None:
        self.deleted.append(rel)

    def resync(self) -> None:
        self.resyncs += 1


def test_watcher_large_batch_schedules_resync(tmp_path):
    queue = _Queue()
    watcher = FileWatcher(tmp_path, queue)  # type: ignore[arg-type]
    watcher._spec = watcher._load_spec()

    changes = {
        (Change.modified, str(tmp_path / f"file_{i}.py"))
        for i in range(MASS_CHANGE_THRESHOLD)
    }
    watcher._handle(changes)

    assert queue.resyncs == 1
    assert queue.reindexed == []
    assert queue.deleted == []


def test_watcher_small_batch_uses_incremental_events(tmp_path):
    queue = _Queue()
    watcher = FileWatcher(tmp_path, queue)  # type: ignore[arg-type]
    watcher._spec = watcher._load_spec()

    added = tmp_path / "a.py"
    removed = tmp_path / "b.py"
    watcher._handle({(Change.added, str(added)), (Change.deleted, str(removed))})

    assert queue.resyncs == 0
    assert queue.reindexed == ["a.py"]
    assert queue.deleted == ["b.py"]
