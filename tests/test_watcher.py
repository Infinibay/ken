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
    watcher._matcher = watcher._load_matcher()

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
    watcher._matcher = watcher._load_matcher()

    added = tmp_path / "a.py"
    removed = tmp_path / "b.py"
    watcher._handle({(Change.added, str(added)), (Change.deleted, str(removed))})

    assert queue.resyncs == 0
    assert queue.reindexed == ["a.py"]
    assert queue.deleted == ["b.py"]


def test_watcher_filters_with_nested_gitignore(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / ".gitignore").write_text("*.env\n")
    queue = _Queue()
    watcher = FileWatcher(tmp_path, queue)  # type: ignore[arg-type]
    watcher._matcher = watcher._load_matcher()

    assert watcher._watch_filter(Change.added, str(tmp_path / "pkg" / "app.py"))
    assert not watcher._watch_filter(Change.added, str(tmp_path / "pkg" / "local.env"))


def test_watcher_nested_gitignore_change_schedules_resync(tmp_path):
    (tmp_path / "pkg").mkdir()
    queue = _Queue()
    watcher = FileWatcher(tmp_path, queue)  # type: ignore[arg-type]
    watcher._matcher = watcher._load_matcher()

    watcher._handle({(Change.modified, str(tmp_path / "pkg" / ".gitignore"))})

    assert queue.resyncs == 1
    assert queue.reindexed == []
    assert queue.deleted == []
