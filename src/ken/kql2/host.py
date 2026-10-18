"""Stable owner of bounded prepared readers, their revisions and source updates."""

from __future__ import annotations

import os
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock, get_ident
from typing import Any

from ken.daemon.watcher import FileWatcher
from ken.structural.service import _configuration
from ken.structural_store.leases import SnapshotExpired

from .execution_control import ExecutionBudget
from .request import RequestCancelled
from .revision import RevisionMonitor, SourceRevision
from .session import QuerySession, SourcesChanged

AUTOMATIC_CACHE_MB = 3000.0
MAX_SESSIONS = 4


def retention(root: Path, override: float | None) -> float:
    if (override is not None or (root / '.ken/structural.json').exists()
            or 'KEN_STRUCTURAL_CACHE_MB' in os.environ):
        return _configuration(root, override)
    return AUTOMATIC_CACHE_MB


@dataclass
class _Reader:
    session: QuerySession
    revision: SourceRevision
    dirty: bool = False
    monitor: RevisionMonitor | None = None

    def unchanged(self) -> bool:
        return self.monitor.unchanged() if self.monitor is not None else self.revision.unchanged()

    def close(self) -> None:
        errors = []
        for resource in (self.monitor, self.session):
            if resource is not None:
                try:
                    resource.close()
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]


class QueryHost:
    """Create, query, refresh and close every session on one owning thread."""

    def __init__(self, root: Path, *, watch: bool = True):
        self.root = root.resolve()
        self._readers: OrderedDict[tuple[str, float, str], _Reader] = OrderedDict()
        self._retiring: list[_Reader] = []
        self._lock = RLock()
        self._epoch = 0
        self._owner = (os.getpid(), get_ident())
        self._closed = False
        from .module_inputs import ModuleResolver
        self._modules = ModuleResolver(self.root)
        self._preparations: deque[tuple[float, float]] = deque(maxlen=2048)
        self._watcher = FileWatcher(self.root, self) if watch else None
        if self._watcher is not None:
            self._watcher.start()

    def _check_owner(self, *, allow_closed: bool = False) -> None:
        if self._owner != (os.getpid(), get_ident()):
            raise RuntimeError('query hosts belong to their creating process and thread')
        if self._closed and not allow_closed:
            raise RuntimeError('query host is closed')

    def reindex(self, rel: str) -> None:
        self.resync()

    def delete(self, rel: str) -> None:
        self.resync()

    def resync(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._epoch += 1
            for reader in self._readers.values():
                reader.dirty = True
                reader.session.invalidate()

    def _ready(self, key: tuple[str, float, str]) -> tuple[_Reader, float]:
        started = time.monotonic()
        with self._lock:
            reader = self._readers.get(key)
        if reader is not None and not reader.dirty and reader.unchanged():
            with self._lock:
                self._readers.move_to_end(key)
            return reader, 0.0
        path, budget, source_profile = key
        if reader is None:
            # Keep ownership until cleanup succeeds; failed eviction blocks
            # admission rather than leaking or growing an unbounded pool.
            while len(self._readers) >= MAX_SESSIONS:
                with self._lock:
                    old_key, old = next(iter(self._readers.items()))
                with self._lock:
                    self._readers.pop(old_key)
                    self._retiring.append(old)
                self._close_retired()
            from .retention import reclaim_before_reader
            reclaim_before_reader(self.root, budget)
        for _ in range(3):
            if reader is not None:
                reader.dirty = True
                if reader.monitor is not None:
                    reader.monitor.close()
                    reader.monitor = None
            with self._lock:
                epoch = self._epoch
            before = SourceRevision.capture(self.root, path)
            try:
                if reader is None:
                    session = QuerySession(self.root, path=path, cache_mb=budget, source_profile=source_profile)
                    reader = _Reader(session, before, dirty=True)
                    with self._lock:
                        self._readers[key] = reader
                else:
                    reader.session.refresh()
            except SourcesChanged:
                continue
            except RequestCancelled:
                # A dirty reader must not resume the abandoned capture from
                # idle maintenance after the request's cancellation scope ends.
                if reader is not None:
                    with self._lock:
                        self._readers.pop(key, None)
                        self._retiring.append(reader)
                    self._close_retired()
                raise
            after = SourceRevision.capture(self.root, path)
            if before == after:
                reader.monitor = RevisionMonitor(after)
                stable = reader.monitor.unchanged()
            else:
                stable = False
            with self._lock:
                self._readers[key] = reader
                self._readers.move_to_end(key)
                if stable and epoch == self._epoch:
                    reader.revision, reader.dirty = after, False
                    break
                reader.dirty = True
                reader.session.invalidate()
        else:
            raise RuntimeError('sources keep changing; retry when the update is stable')
        finished = time.monotonic()
        self._preparations.append((started, finished))
        return reader, (finished - started) * 1000

    def search(self, source: str | None = None, *, saved_query: str | None = None, path: str = '.', cache_mb: float | None = None,
               timeout_ms: float | None = None, arrived_at: float | None = None,
               **options: Any) -> dict[str, Any]:
        processing = time.monotonic()
        started = processing if arrived_at is None else arrived_at
        index_wait_ms = sum(max(0.0, min(end, processing) - max(begin, started)) * 1000
                            for begin, end in self._preparations)
        self._check_owner()
        from .module_inputs import ResolvedQuery, validate_entry

        validate_entry(source, saved_query)
        self._close_retired()
        ExecutionBudget(timeout_ms, options.get('max_states'), options.get('max_rows'))
        from .compilation import compile_query
        from .local_hazards import supports as local_hazards

        budget = retention(self.root, cache_mb)
        def profile_for(resolved: ResolvedQuery) -> str:
            prepared, _, _ = compile_query(self.root, resolved.source, resolved.query_name,
                                           budget_bytes=int(budget * 1_000_000), read_disk=False,
                                           reference=options.get('reference', False), libraries=resolved.libraries)
            return ('local_hazards' if not options.get('reference', False)
                    and local_hazards(prepared.program) else 'full')

        resolved = self._modules.resolve(source, saved_query=saved_query,
                                         query_name=options.get('query_name'),
                                         libraries=options.get('libraries'))
        key = (path, budget, profile_for(resolved))
        preparation_ms = 0.0
        for _ in range(3):
            reader, prepared_ms = self._ready(key)
            preparation_ms += prepared_ms
            with self._lock:
                epoch = self._epoch
            try:
                resolved = reader.session.resolve_query(
                    source, saved_query=saved_query, query_name=options.get('query_name'), libraries=options.get('libraries'),
                )
                current_key = (path, budget, profile_for(resolved))
                if current_key != key:
                    key = current_key
                    continue
                query_options = {**options, 'query_name': resolved.query_name, 'libraries': resolved.libraries}
                graph_started = time.monotonic()
                graph_ms = reader.session.prepare_query(
                    resolved.source, query_name=resolved.query_name, libraries=resolved.libraries,
                    reference=options.get('reference', False),
                )
                preparation_ms += graph_ms
                if graph_ms:
                    finished = time.monotonic()
                    self._preparations.append((max(graph_started, finished - graph_ms / 1000), finished))
                elapsed = (time.monotonic() - started) * 1000 - preparation_ms - index_wait_ms
                result = reader.session.search(
                    resolved.source, timeout_ms=None if timeout_ms is None else max(0.0, timeout_ms - elapsed),
                    **query_options,
                )
            except (SourcesChanged, SnapshotExpired):
                reader.dirty = True
                reader.session.invalidate()
                continue
            unchanged = reader.unchanged()
            with self._lock:
                invalidated = reader.dirty or epoch != self._epoch
            if (result.get('reason') in {'snapshot_invalidated', 'snapshot_expired'}
                    or invalidated or not unchanged):
                reader.dirty = True
                reader.session.invalidate()
                continue
            result['analysis'].update(
                freshness='verified_snapshot', preparation_ms=preparation_ms,
                freshness_backend=reader.monitor.backend if reader.monitor is not None else 'metadata',
                index_wait_ms=index_wait_ms,
                total_ms=(time.monotonic() - started) * 1000,
                prepared_query_ms=(time.monotonic() - started) * 1000 - preparation_ms - index_wait_ms,
                session_pid=os.getpid(),
            )
            if (timeout_ms is not None and result['analysis']['prepared_query_ms'] >= timeout_ms
                    and result['complete']):
                result['complete'], result['reason'] = False, 'timeout'
            return resolved.annotate(result)
        raise RuntimeError('sources keep changing; retry when the update is stable')

    def maintain(self) -> None:
        """Refresh edits and maintain protection while the service is idle."""
        self._check_owner()
        self._close_retired()
        with self._lock:
            readers = list(self._readers.items())
        for key, reader in readers:
            try:
                reader.session.maintain()
            except SnapshotExpired:
                reader.dirty = True
            self._ready(key)

    def close(self) -> None:
        self._check_owner(allow_closed=True)
        self._closed = True
        errors: list[BaseException] = []
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._watcher = None
        with self._lock:
            self._retiring.extend(self._readers.values())
            self._readers.clear()
        try:
            self._close_retired()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._modules.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise errors[0]

    def _close_retired(self) -> None:
        """Keep failed cleanup owned, without exposing closing readers to queries."""
        errors: list[BaseException] = []
        for reader in list(self._retiring):
            try:
                reader.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._retiring.remove(reader)
        if errors:
            raise errors[0]

    def __enter__(self) -> QueryHost:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
