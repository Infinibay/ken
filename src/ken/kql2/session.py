"""Repeated queries against an explicitly prepared and pinned source revision."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from os import getpid
from pathlib import Path
from threading import Lock, get_ident
from typing import Any

from ken.structural.service import _configuration
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.leases import SnapshotExpired, pin, renew
from ken.structural_store.store import MIN_PERSISTENT_MB

from .catalog import packaged_libraries
from .compilation import compile_query
from .compiler import Program
from .execution import execute
from .execution_control import ExecutionBudget
from .module_inputs import ModuleResolver, ResolvedQuery
from .reporting import query_response
from .service import search
from .semantic import SemanticRelations, requires_semantics
from .semantic_index import SemanticIndex

_CAPTURE_QUERY = 'language "kql/2"; module ken.session; query capture {select 1;}'
_CAPTURE_HAZARDS = '''language "kql/2"; module ken.session;
query capture {edge HAS_HAZARD($site,$kind); select $site;}'''


class SourcesChanged(RuntimeError):
    """The revision must be prepared again before delivering a current answer."""


class PersistentStorageRequired(ValueError):
    """A prepared reader cannot retain its revision under this storage budget."""


class QuerySession:
    """Own one source reader; refresh sources outside the query boundary.

    A session reads its captured revision until refresh. It never caches query
    answers or silently recaptures source files in the middle of a query.
    """

    def __init__(
        self,
        root: Path,
        *,
        path: str = ".",
        cache_mb: float | None = None,
        max_file_bytes: int = 2_000_000,
        source_paths: list[str] | None = None,
        source_profile: str = "full",
    ):
        self.root = Path(root).resolve()
        self.path = path
        self.cache_mb = cache_mb
        self.max_file_bytes = max_file_bytes
        self.source_paths = None if source_paths is None else tuple(source_paths)
        if source_profile not in {"full", "local_hazards"}:
            raise ValueError('unsupported preparation profile')
        self.source_profile = source_profile
        self._owner = get_ident()
        self._process = getpid()
        self._closed = False
        self._revision_lock = Lock()
        self._epoch = 0
        self._dirty = False
        self._store: Store | None = None
        self._metadata: dict[str, Any] = {}
        self._coverage = False
        self._unit_count = 0
        self._libraries: dict[str, str] = {}
        self._graph_index: GraphIndex | None = None
        self._semantic_index: SemanticIndex | None = None
        self._modules = ModuleResolver(self.root)
        self.refresh()

    def _check_owner(self) -> None:
        if getpid() != self._process or get_ident() != self._owner:
            raise RuntimeError("query sessions belong to their creating process and thread")
        if self._closed:
            raise RuntimeError("query session is closed")

    def invalidate(self) -> None:
        """Mark changed inputs; this notification may come from a watcher thread."""
        with self._revision_lock:
            self._epoch += 1
            self._dirty = True

    def refresh(self) -> None:
        self._check_owner()
        with self._revision_lock:
            epoch = self._epoch
        budget = _configuration(self.root, self.cache_mb)
        disk_budget = budget - min(budget / 5, 100)
        if disk_budget < MIN_PERSISTENT_MB:
            raise PersistentStorageRequired("prepared query sessions require retained source storage; increase cache_mb")
        # A building lease protects capture until this reader pins its revision.
        # Opening after search returns would leave an observable GC race.
        reader = Store(
            self.root / ".ken/structural/v2/store.sqlite",
            cache_mb=disk_budget,
        )
        try:
            captured = search(
                self.root, _CAPTURE_HAZARDS if self.source_profile == 'local_hazards' else _CAPTURE_QUERY,
                path=self.path,
                cache_mb=self.cache_mb, max_file_bytes=self.max_file_bytes,
                source_paths=None if self.source_paths is None else list(self.source_paths),
            )
            libraries = packaged_libraries()
            metadata = captured["analysis"]
            if metadata["ephemeral"]:
                raise PersistentStorageRequired("prepared query sessions require retained source storage; increase cache_mb")
            pin(reader, metadata["snapshot"])
            unit_count = reader.db.execute(
                "SELECT count(*) FROM k2_snapshot_units WHERE snapshot_id=?",
                (metadata["snapshot"],),
            ).fetchone()[0]
            # Queries must not wait for another writer during lease renewal.
            # Acquisition retains Store's normal wait policy on its own reader.
            reader.db.execute("PRAGMA busy_timeout=0")
            reader.defer_busy_renewal = True
            retain_reader = self._retains_snapshot(reader, metadata)
            with self._revision_lock:
                if self._epoch != epoch:
                    raise SourcesChanged("sources changed during refresh; refresh again")
                # A filesystem notification need not change the source snapshot.
                # Keep its live reader and immutable indexes; release the fresh
                # acquisition reader instead. Expired readers are never reused.
                previous = reader if retain_reader else self._store
                previous_semantics = None if retain_reader else self._semantic_index
                previous_graph = None if retain_reader else self._graph_index
                if not retain_reader:
                    self._store = reader
                    self._graph_index = None
                    self._semantic_index = None
                self._metadata = metadata
                self._coverage = captured["coverage_complete"]
                self._unit_count = unit_count
                self._libraries = libraries
                self._dirty = False
        except BaseException:
            reader.close()
            raise
        try:
            if previous_semantics is not None:
                previous_semantics.close()
        finally:
            try:
                if previous_graph is not None:
                    previous_graph.close()
            finally:
                if previous is not None:
                    previous.close()

    def _retains_snapshot(self, reader: Store, metadata: dict[str, Any]) -> bool:
        """Reuse a live reader only for the identical captured storage revision."""
        previous = self._store
        if (previous is None or previous.path != reader.path
                or any(self._metadata.get(key) != metadata[key]
                       for key in ('snapshot', 'frontend', 'cache_mb', 'disk_budget_mb'))):
            return False
        params = (metadata['snapshot'],)
        old = previous.db.execute('SELECT manifest FROM k2_snapshots WHERE snapshot_id=?', params).fetchone()
        current = reader.db.execute('SELECT manifest FROM k2_snapshots WHERE snapshot_id=?', params).fetchone()
        if old is None or old != current:
            return False
        try:
            self._check_lease(previous)
        except SnapshotExpired:
            return False
        return True

    def _check_profile(self, program: Program, reference: bool) -> None:
        from .local_hazards import supports

        if self.source_profile == 'local_hazards' and (reference or not supports(program)):
            raise ValueError('local hazard preparation cannot answer a full-source query')

    def search(
        self,
        source: str | None = None,
        *,
        saved_query: str | None = None,
        query_name: str | None = None,
        libraries: Mapping[str, str] | None = None,
        reference: bool = False,
        profile: bool = False,
        timeout_ms: float | None = None,
        max_states: int | None = None,
        max_rows: int | None = None,
        cancelled: Callable[[], bool] | None = None,
        include_entities: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        ExecutionBudget(timeout_ms, max_states, max_rows)
        from . import request

        self._check_owner()
        resolved = self.resolve_query(source, saved_query=saved_query, query_name=query_name, libraries=libraries)
        source, query_name, libraries = resolved.source, resolved.query_name, resolved.libraries
        with self._revision_lock:
            if self._dirty:
                raise SourcesChanged("sources invalidated; refresh before querying")
            epoch = self._epoch
        store = self._store
        if store is None:
            raise RuntimeError("query session is closed")
        request.phase(
            "compile", lease_id=store.lease_id, database=str(store.path),
            query=query_name, columns=[],
            result={"language": "kql/2", "query": query_name, "columns": [], "rows": [],
                    "complete": False, "coverage_complete": self._coverage,
                    "unknown_candidates": 0, "results_truncated": False},
        )
        prepared, state, compilation = compile_query(
            self.root, source, query_name,
            budget_bytes=int(self._metadata["cache_mb"] * 1_000_000),
            read_disk=False, reference=reference,
            libraries=libraries,
        )
        compile_ms = (time.monotonic() - started) * 1000
        self._check_profile(prepared.program, reference)
        request.phase("query", query=prepared.program.name, columns=[
            expr.value or f"column_{i + 1}" for i, expr in enumerate(prepared.program.projection)
        ])
        try:
            self._check_lease(store)
        except SnapshotExpired:
            from .outcome import Outcome

            outcome = Outcome(complete=False, reason="snapshot_expired")
        else:
            outcome = execute(
                prepared.program, store, self._metadata["snapshot"],
                prepared_plans=dict(prepared.plans),
                reference=reference, profile=profile,
                timeout_ms=request.remaining(
                    None if timeout_ms is None
                    else max(0.0, timeout_ms - (time.monotonic() - started) * 1000)
                ),
                max_states=max_states, max_rows=max_rows, cancelled=cancelled,
                semantic_index=self._semantic_index,
                prepared_graph=self._graph_index,
            )
        program = prepared.program
        response = query_response(program, outcome, self._coverage)
        from .diagnostics import diagnose

        diagnostics = diagnose(program)
        if diagnostics:
            response["diagnostics"] = diagnostics
        response["analysis"] = {
            "snapshot": self._metadata["snapshot"],
            "frontend": self._metadata["frontend"],
            "freshness": "captured_snapshot",
            "source_profile": self.source_profile,
            "parsed_units": 0,
            "reused_units": self._unit_count,
            "cache_mb": self._metadata["cache_mb"],
            "disk_budget_mb": self._metadata["disk_budget_mb"],
            "compilation_cache": {**compilation, "status": state},
            "result_cache": "disabled",
            "ephemeral": False,
            "states": outcome.states,
            "scanned_nodes": outcome.scanned_nodes,
            "compile_ms": compile_ms,
            "build_ms": 0.0,
            "query_ms": outcome.elapsed_ms,
            "total_ms": (time.monotonic() - started) * 1000,
            "semantic_storage": self._semantic_index.storage if self._semantic_index is not None else None,
        }
        if self.source_paths is not None:
            response["source_scope"] = {"kind": "explicit_files", "paths": sorted(set(self.source_paths))}
        if include_entities:
            from ken.structural_store.node_locations import locations

            identities = {
                value if isinstance(value, str) else value.get("local_id", "")
                for row in response["rows"] for value in row
                if isinstance(value, (str, dict))
            }
            response["entities"] = locations(store, self._metadata["snapshot"], identities)
        if profile:
            response["analysis"]["operator_profile"] = outcome.profile
        self._finish_delivery(response, started, timeout_ms, epoch)
        request.phase("report", result=response)
        self._finish_delivery(response, started, timeout_ms, epoch)
        return resolved.annotate(response)

    def _check_lease(self, store: Store) -> None:
        renew(store)
        live = store.db.execute(
            "SELECT 1 FROM k2_leases WHERE lease_id=? AND snapshot_id=? AND expires_ns>?",
            (store.lease_id, self._metadata["snapshot"], time.time_ns()),
        ).fetchone()
        if live is None:
            raise SnapshotExpired("snapshot lease expired; refresh the session")

    def _finish_delivery(
        self, response: dict[str, Any], started: float,
        timeout_ms: float | None, epoch: int,
    ) -> bool:
        """Reject stale or late success at the delivery boundary."""
        from . import request

        elapsed = (time.monotonic() - started) * 1000
        response["analysis"]["total_ms"] = elapsed
        with self._revision_lock:
            invalidated = self._dirty or self._epoch != epoch
        reason = None
        if invalidated:
            reason = "snapshot_invalidated"
        elif (timeout_ms is not None and elapsed >= timeout_ms) or request.expired():
            reason = "timeout"
        if response["complete"] and reason:
            response["complete"], response["reason"] = False, reason
            return True
        return False

    def search_json(self, source: str | None = None, **options: Any) -> str:
        """Deliver JSON within the same cooperative query deadline."""
        started = time.monotonic()
        with self._revision_lock:
            epoch = self._epoch
        response = self.search(source, **options)
        # Encode each part once, then append elapsed time after encoding. An
        # interrupted delivery is re-encoded only to correct its success flag.
        body = {key: value for key, value in response.items() if key != "analysis"}
        analysis = {key: value for key, value in response["analysis"].items() if key != "total_ms"}
        encoded_body = json.dumps(body, separators=(",", ":"))
        encoded_analysis = json.dumps(analysis, separators=(",", ":"))
        if self._finish_delivery(response, started, options.get("timeout_ms"), epoch):
            return json.dumps(response, separators=(",", ":"))
        encoded = (
            encoded_body[:-1] + ',"analysis":' + encoded_analysis[:-1]
            + ',"total_ms":' + repr(response["analysis"]["total_ms"]) + '}}'
        )
        if self._finish_delivery(response, started, options.get("timeout_ms"), epoch):
            return json.dumps(response, separators=(",", ":"))
        return encoded

    def prepare_graph(self) -> None:
        """Prepare semantic graph data outside the latency boundary."""
        self._check_owner()
        with self._revision_lock:
            if self._dirty:
                raise SourcesChanged("sources invalidated; refresh before preparing graph")
        store = self._store
        if store is None:
            raise RuntimeError("query session is closed")
        self._check_lease(store)
        if self._graph_index is not None:
            return
        from .graph_execution import graph_index
        from ken.structural_store.graph_index import GraphIndex

        def check():
            from .request import check_cancelled
            check_cancelled()
            renew(store)
        index, _ = graph_index(store, self._metadata["snapshot"], check)
        assert isinstance(index, GraphIndex)
        with self._revision_lock:
            dirty = self._dirty
        if dirty:
            index.close()
            raise SourcesChanged('sources invalidated while preparing graph')
        self._graph_index = index

    def resolve_query(self, source: str | None = None, *, saved_query: str | None = None,
                      query_name: str | None = None,
                      libraries: Mapping[str, str] | None = None) -> ResolvedQuery:
        """Bind a query and its import closure to one registry snapshot."""
        self._check_owner()
        return self._modules.resolve(source, saved_query=saved_query, query_name=query_name,
                                     libraries=libraries, packaged=self._libraries)

    def prepare_query(self, source: str | None = None, *, saved_query: str | None = None, query_name: str | None = None,
                      libraries: Mapping[str, str] | None = None,
                      reference: bool = False) -> float:
        """Prepare demanded graph/BODY facts before the caller's query budget."""
        self._check_owner()
        resolved = self.resolve_query(source, saved_query=saved_query, query_name=query_name, libraries=libraries)
        source, query_name, libraries = resolved.source, resolved.query_name, resolved.libraries
        prepared, _, _ = compile_query(
            self.root, source, query_name,
            budget_bytes=int(self._metadata["cache_mb"] * 1_000_000),
            read_disk=False, reference=reference,
            libraries=libraries,
        )
        self._check_profile(prepared.program, reference)
        with self._revision_lock:
            if self._dirty:
                raise SourcesChanged("sources invalidated; refresh before preparing query")
        programs = prepared.program.branches or (prepared.program,)
        from .local_hazards import supports as local_hazards

        graph_needed = self._graph_index is None and any(
            program.graph and (reference or not local_hazards(program))
            for program in programs
        )
        semantics_needed = self._semantic_index is None and requires_semantics(prepared.program)
        if not graph_needed and not semantics_needed:
            return 0.0
        started = time.monotonic()
        if graph_needed:
            self.prepare_graph()
        if semantics_needed:
            self.prepare_semantics()
        return (time.monotonic() - started) * 1000

    def prepare_semantics(self) -> None:
        """Retain snapshot facts in shared storage or a session-owned disk spill."""
        self._check_owner()
        store = self._store
        if store is None:
            raise RuntimeError('query session is closed')
        def check():
            from .request import check_cancelled
            check_cancelled()
            with self._revision_lock:
                if self._dirty:
                    raise SourcesChanged('sources invalidated; refresh before preparing semantics')
            self._check_lease(store)
        check()
        if self._semantic_index is not None:
            return
        semantic = SemanticRelations(store, self._metadata['snapshot'], check)
        semantic.prepare(retain=True)
        index = semantic.prepared_index
        assert index is not None
        try:
            check()
        except BaseException:
            index.close()
            raise
        self._semantic_index = index

    def maintain(self) -> None:
        """Keep the captured revision protected while its owning service is idle."""
        self._check_owner()
        if self._store is None:
            raise RuntimeError("query session is closed")
        self._check_lease(self._store)

    def close(self) -> None:
        if getpid() != self._process or get_ident() != self._owner:
            raise RuntimeError("query sessions belong to their creating process and thread")
        self._closed = True
        try:
            try:
                if self._semantic_index is not None:
                    index, self._semantic_index = self._semantic_index, None
                    index.close()
            finally:
                try:
                    if self._graph_index is not None:
                        graph, self._graph_index = self._graph_index, None
                        graph.close()
                finally:
                    if self._store is not None:
                        store, self._store = self._store, None
                        store.close()
        finally:
            self._modules.close()

    def __enter__(self) -> QuerySession:
        self._check_owner()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
