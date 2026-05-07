"""Filesystem watcher that feeds the IndexQueue.

Wraps ``watchfiles.watch`` (Rust-backed inotify on Linux, FSEvents on
macOS) in a daemon thread.  Per FS event:

* added / modified  → ``IndexQueue.reindex(rel_path)``
* deleted           → ``IndexQueue.delete(rel_path)``

Filtering happens **before** an event becomes a queue entry — we don't
want to even acknowledge writes inside `.ken/` (we'd echo our own DB
journals back at ourselves).  The filter composes:

1. ``ALWAYS_IGNORE`` from ``gitignore_filter`` (.git/, .ken/, .venv/, …),
2. the project root's ``.gitignore`` (loaded once at watcher start,
   reloaded on changes to that file).

Shutdown is cooperative: ``watch()`` accepts a ``stop_event`` —
flipping it returns the generator immediately.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from pathspec import GitIgnoreSpec
from watchfiles import Change, watch

from ken.daemon.index_queue import IndexQueue
from ken.gitignore_filter import ALWAYS_IGNORE

logger = logging.getLogger("ken.watcher")

# How long watchfiles batches events before flushing to us. 200ms is
# tight enough to feel live in a save-and-rerun loop, loose enough to
# absorb the truncate+write pair vim emits per save.
DEBOUNCE_MS = 200


class FileWatcher:
    """Background thread that pushes filesystem changes into IndexQueue."""

    def __init__(self, project_root: Path, queue: IndexQueue) -> None:
        self.project_root = project_root.resolve()
        self.queue = queue
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Built lazily in start() so a slow .gitignore parse doesn't run
        # on the wrong thread.
        self._spec: GitIgnoreSpec | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._spec = self._load_spec()
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
        # Reload .gitignore if the file itself changed — keeps the spec
        # honest after a `git pull` rewrites it.
        gi_path = self.project_root / ".gitignore"
        if any(p == str(gi_path) for _, p in changes):
            self._spec = self._load_spec()

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
        spec = self._spec
        if spec is None:
            return True
        # gitignore matches dirs only with a trailing slash. We don't
        # know if a deleted entry was a dir from the path alone, so try
        # both: if either form matches the ignore set, drop the event.
        if spec.match_file(rel) or spec.match_file(rel + "/"):
            return False
        return True

    def _load_spec(self) -> GitIgnoreSpec:
        patterns = list(ALWAYS_IGNORE)
        gi = self.project_root / ".gitignore"
        if gi.is_file():
            try:
                patterns.extend(gi.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                pass
        return GitIgnoreSpec.from_lines(patterns)
