"""Filesystem watcher that feeds the IndexQueue.

Wraps ``watchfiles.watch`` (Rust-backed inotify on Linux, FSEvents on
macOS) in a daemon thread.  Per FS event:

* added / modified  → ``IndexQueue.reindex(rel_path)``
* deleted           → ``IndexQueue.delete(rel_path)``

Filtering happens **before** an event becomes a queue entry — we don't
want to even acknowledge writes inside `.ken/` (we'd echo our own DB
journals back at ourselves). The filter composes ``ALWAYS_IGNORE`` from
``gitignore_filter`` with every applicable `.gitignore` from the project
root down to the event's parent directory.

Shutdown is cooperative: ``watch()`` accepts a ``stop_event`` —
flipping it returns the generator immediately.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchfiles import Change, watch

from ken.daemon.index_queue import IndexQueue
from ken.gitignore_filter import GitignoreMatcher

logger = logging.getLogger("ken.watcher")

# How long watchfiles batches events before flushing to us. 200ms is
# tight enough to feel live in a save-and-rerun loop, loose enough to
# absorb the truncate+write pair vim emits per save.
DEBOUNCE_MS = 200
MASS_CHANGE_THRESHOLD = 512


class FileWatcher:
    """Background thread that pushes filesystem changes into IndexQueue."""

    def __init__(self, project_root: Path, queue: IndexQueue) -> None:
        self.project_root = project_root.resolve()
        self.queue = queue
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Built lazily in start() so gitignore parsing doesn't run on the
        # wrong thread.
        self._matcher: GitignoreMatcher | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._matcher = self._load_matcher()
        self._thread = threading.Thread(target=self._run, name="ken-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    # ---- internals -------------------------------------------------------

    def _run(self) -> None:
        try:
            for changes in watch(
                str(self.project_root),
                stop_event=self._stop_event,
                debounce=DEBOUNCE_MS,
                recursive=True,
                watch_filter=self._watch_filter,
            ):
                self._handle(changes)
        except Exception:  # pragma: no cover - watchfiles is robust in practice
            logger.exception("watcher loop crashed")

    def _handle(self, changes: set[tuple[Change, str]]) -> None:
        # Reload if any gitignore changed. A pattern change can make
        # already-indexed paths stale, so ask the queue for a full resync.
        if any(Path(p).name == ".gitignore" for _, p in changes):
            self._matcher = self._load_matcher()
            logger.info("gitignore changed; scheduling index resync")
            self.queue.resync()
            return

        if len(changes) >= MASS_CHANGE_THRESHOLD:
            logger.info("large filesystem batch detected; scheduling index resync")
            self.queue.resync()
            return

        for change, abs_path in changes:
            rel = self._rel(abs_path)
            if rel is None:
                continue
            if change is Change.deleted:
                self.queue.delete(rel)
            else:
                self.queue.reindex(rel)

    def _rel(self, abs_path: str) -> str | None:
        try:
            p = Path(abs_path)
            return p.resolve().relative_to(self.project_root).as_posix()
        except (ValueError, OSError):
            return None

    def _watch_filter(self, change: Change, path: str) -> bool:
        """Return True to keep, False to drop. Called for *every* FS event."""
        del change  # currently we accept all change types; filtering is path-based
        try:
            rel = Path(path).resolve().relative_to(self.project_root).as_posix()
        except (ValueError, OSError):
            return False
        if not rel:
            return False
        matcher = self._matcher
        if matcher is None:
            return True
        if matcher.is_ignored(Path(rel)) or matcher.is_ignored(Path(rel), is_dir=True):
            return False
        return True

    def _load_matcher(self) -> GitignoreMatcher:
        return GitignoreMatcher(self.project_root)
