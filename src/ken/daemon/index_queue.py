"""Background re-index queue used by the daemon.

The watcher pushes ``(action, rel_path)`` tuples here as files change;
a single worker thread pulls them off, dedupes by path, and applies
them in batches.  Owns its own SQLite connection so the HTTP server
isn't blocked during a fan-in (e.g. ``git checkout`` of a big branch
emits hundreds of changes at once).

Why not run the indexer inline in the watcher thread? Two reasons:

1. **Coalescing**: a save in vim emits two FS events (truncate + write)
   ~5ms apart. We want a single reindex per logical save, not two.
2. **Batching**: when 1000 files change at once we want the queue worker
   to process them in one ``BEGIN; ... COMMIT;`` rather than 1000 tiny
   transactions.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ken import _paths
from ken.db import connect
from ken.gitignore_filter import iter_files
from ken.indexer import IndexStats, delete_file, index_files

if False:  # TYPE_CHECKING-only — avoid heavy fastembed import at queue start
    from ken.embedder import Embedder

logger = logging.getLogger("ken.queue")

Action = Literal["reindex", "delete", "resync"]
BATCH_DRAIN_S = 0.5
BATCH_MAX_SIZE = 256


@dataclass
class _Event:
    action: Action
    rel: str


class IndexQueue:
    """Thread-safe queue + worker for incremental reindexing."""

    def __init__(
        self,
        project_root: Path,
        *,
        embedder: "Embedder | None" = None,
        on_batch: Callable[[IndexStats, int], None] | None = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self._on_batch = on_batch
        self._embedder = embedder
        self._queue: queue.Queue[_Event | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Indexer thread owns its own connection — keeps long-running
        # batches off the HTTP server's lock.
        self._conn: sqlite3.Connection | None = None

    # ---- public surface --------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._conn = connect(_paths.db_path(self.project_root))
        self._thread = threading.Thread(target=self._run, name="ken-indexer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._queue.put(None)  # nudge a blocked .get()
        self._thread.join(timeout=timeout)
        self._thread = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def reindex(self, rel: str) -> None:
        self._queue.put(_Event(action="reindex", rel=rel))

    def delete(self, rel: str) -> None:
        self._queue.put(_Event(action="delete", rel=rel))

    def resync(self) -> None:
        self._queue.put(_Event(action="resync", rel=""))

    # ---- worker ----------------------------------------------------------

    def _run(self) -> None:
        assert self._conn is not None
        while not self._stop.is_set():
            try:
                head = self._queue.get(timeout=BATCH_DRAIN_S)
            except queue.Empty:
                continue
            if head is None:
                return
            batch = self._drain_batch(head)
            self._apply(batch)

    def _drain_batch(self, head: _Event) -> dict[str, Action]:
        """Coalesce up to BATCH_MAX_SIZE events into a path → action map.

        Last writer wins per path: if the same file is touched twice in
        a debounce window we only run one reindex on it.  A reindex
        followed by a delete (or vice-versa) collapses to whichever came
        last — matches the on-disk state we'll observe when we run.
        """
        if head.action == "resync":
            self._discard_pending_events()
            return {"": "resync"}
        batch: dict[str, Action] = {head.rel: head.action}
        deadline = time.monotonic() + BATCH_DRAIN_S
        while time.monotonic() < deadline and len(batch) < BATCH_MAX_SIZE:
            try:
                ev = self._queue.get_nowait()
            except queue.Empty:
                break
            if ev is None:
                # Stop sentinel — process what we have, then return.
                break
            if ev.action == "resync":
                self._discard_pending_events()
                return {"": "resync"}
            batch[ev.rel] = ev.action
        return batch

    def _apply(self, batch: dict[str, Action]) -> None:
        assert self._conn is not None
        if not batch:
            return
        if "resync" in batch.values():
            self._apply_resync()
            return
        reindex_paths = [Path(rel) for rel, action in batch.items() if action == "reindex"]
        delete_paths = [rel for rel, action in batch.items() if action == "delete"]
        deleted = 0
        for rel in delete_paths:
            if delete_file(self._conn, rel):
                deleted += 1
        stats = IndexStats()
        if reindex_paths:
            stats = index_files(
                self._conn,
                self.project_root,
                reindex_paths,
                on_progress=None,
                embedder=self._embedder,
            )
        if deleted or stats.parsed or stats.unchanged:
            logger.info(
                "indexed batch parsed=%s unchanged=%s deleted=%s no-parser=%s",
                stats.parsed,
                stats.unchanged,
                deleted,
                stats.skipped_no_lang,
            )
        if self._on_batch is not None:
            self._on_batch(stats, deleted)

    def _discard_pending_events(self) -> None:
        while True:
            try:
                ev = self._queue.get_nowait()
            except queue.Empty:
                return
            if ev is None:
                self._queue.put(None)
                return

    def _apply_resync(self) -> None:
        assert self._conn is not None
        rels = list(iter_files(self.project_root))
        current = {rel.as_posix() for rel in rels}
        rows = self._conn.execute("SELECT path FROM ci_files").fetchall()
        stale = [row["path"] for row in rows if row["path"] not in current]

        deleted = 0
        for rel in stale:
            if delete_file(self._conn, rel):
                deleted += 1

        stats = index_files(
            self._conn,
            self.project_root,
            rels,
            on_progress=None,
            embedder=self._embedder,
        )
        logger.info(
            "resynced index parsed=%s unchanged=%s deleted=%s no-parser=%s",
            stats.parsed,
            stats.unchanged,
            deleted,
            stats.skipped_no_lang,
        )
        if self._on_batch is not None:
            self._on_batch(stats, deleted)
