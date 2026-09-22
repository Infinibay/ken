"""Acquire/reuse executable query indexes independently of result caches."""

from __future__ import annotations

import time
from contextlib import closing, contextmanager
from pathlib import Path

from ken._paths import resolve_project_path
from ken.structural_store import Store
from ken.structural_store.acquisition import AcquisitionLock
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish
from ken.structural_store.graph_revision import graph_revision

from .cache import IRCache
from .model import IR_VERSION


@contextmanager
def project_index(
    root: Path,
    *,
    path=".",
    cache_mb=None,
    max_files=None,
    max_file_bytes=2_000_000,
    database: Path | None = None,
    source_cache_path: Path | None = None,
):
    from ken.kql2.compilation import implementation_fingerprint

    from .query_view import normalize_query_graph
    from .service import (
        _configuration,
        _parser_versions,
        build_project,
        source_manifest,
    )

    started = time.monotonic()
    phases = {}

    @contextmanager
    def phase(name):
        phase_started = time.monotonic()
        try:
            yield
        finally:
            phases[name] = round((time.monotonic() - phase_started) * 1000, 3)

    root = root.resolve()
    target = resolve_project_path(root, path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")
    if (max_files is not None and max_files <= 0) or max_file_bytes <= 0:
        raise ValueError("scan limits must be positive")
    enabled = _configuration(root, cache_mb) > 0
    versions = _parser_versions()
    with phase("manifest"):
        manifest, skipped = source_manifest(
            root, target, versions, max_files, max_file_bytes
        )
    graph_key = IRCache.key(
        "project", IR_VERSION, versions, *(key for _, key, _ in manifest)
    )
    key = IRCache.key(
        # Prefer the operation-column encoding after upgrading. Source-unit
        # cache keys stay unchanged; older readers may finish on the old graph.
        "native-query-index/2",
        graph_key,
        graph_revision(),
    )
    database = database or root / ".ken/structural/v2/patterns.sqlite"
    # The executable index is source data, not a cached JSON artifact. A 500 MB
    # result-cache quota must not force a multi-million-row index back into RAM.
    with closing(AcquisitionLock(database, enabled=enabled)) as acquisition:
        with phase("store_open"):
            store: Store | None = Store(database, cache_mb=None if enabled else 0)
        index = None
        try:
            assert store is not None
            found = store.db.execute(
                "SELECT graph_id,snapshot_id FROM k2_graphs JOIN k2_graph_publications USING(graph_id) WHERE fingerprint=? AND ready=1",
                (key,),
            ).fetchone()
            if found:
                from ken.structural_store.leases import pin

                pin(store, found[1])
                with phase("index_open"):
                    index = GraphIndex(store, found[0])
                analysis = dict(index.analysis)
                analysis["skipped"] = skipped
                analysis["coverage_complete"] = not skipped and not index.ir.diagnostics
                analysis["cache"] = {
                    "hits": 1,
                    "misses": 0,
                    "evictions": 0,
                    "enabled": enabled,
                    "error": None,
                }
            else:
                store.close()
                store = None
                with phase("source_build"):
                    raw, analysis = build_project(
                        root,
                        path=path,
                        cache_mb=cache_mb,
                        max_files=max_files,
                        max_file_bytes=max_file_bytes,
                        _manifest=(manifest, skipped),
                        _cache_project=False,
                        _cache_path=source_cache_path,
                    )
                with phase("normalization"):
                    normalized = normalize_query_graph(raw)
                del raw
                failed = len(analysis["files"]) != len(manifest)
                persistent = enabled and not failed
                store = Store(database, cache_mb=None if persistent else 0)
                snapshot = store.publish(
                    [],
                    expected_parent=store.current,
                    profile=key,
                    complete=analysis["coverage_complete"],
                )
                with phase("index_write"):
                    graph = publish(
                        store,
                        snapshot,
                        key,
                        normalized,
                        analysis=analysis,
                        consume=True,
                    )
                del normalized
                with phase("index_open"):
                    index = GraphIndex(store, graph)
            analysis["graph_key"] = (
                IRCache.key(key, implementation_fingerprint())
                if len(analysis["files"]) == len(manifest)
                else ""
            )
            assert store is not None
            from ken.structural_store.leases import collect

            reclaimed = collect(store, retain=1)
            analysis["query_index"] = {
                "backend": "sqlite_columns",
                "hit": bool(found),
                "persistent": store.path is not None,
                "bytes": store.allocated_bytes,
                "entities": len(index.ir.entities),
                "facts": len(index.ir.facts),
                "reclaimed_snapshots": reclaimed["snapshots"],
                "phase_ms": phases,
            }
            analysis["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
            # Acquisition is finished; independent readers need not wait for the
            # duration of catalogue matching. The snapshot lease remains pinned.
            acquisition.close()
            yield index, analysis
        finally:
            if index is not None:
                index.close()
            if store is not None:
                store.close()
