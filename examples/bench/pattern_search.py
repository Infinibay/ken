"""Measure the GoF catalog against a real repository, without changing that repo.

Example (unlimited queries by default)::

    python examples/bench/pattern_search.py ../codex --artifacts /tmp/pattern-bench

Use --timeout-ms for diagnosis, --profile for cProfile/operator breakdowns.
An explicit --snapshot reuses a trusted, locally generated pickle so baseline
and candidate run on identical input. Never load snapshots from other sources.
Result caching is bypassed; preparation and query times are reported separately.
"""

from __future__ import annotations

import argparse
import cProfile
import gc
import hashlib
import json
import pickle
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from ken.structural import service
from ken.structural.cache import IRCache
from ken.structural.model import IR, FactIndex
from ken.structural.query import QueryBudget
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.rules import builtin_rules, query_registry


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def semantic_result(value):
    """Ignore evidence ordering and versioned compilation IDs, not evidence.

    Saved outcomes retain the original data. Only the comparison fingerprint
    strips a compiler hash from a named-query reference; the qualified query
    name, bindings, source locations, paths and uncertainty remain included.
    """
    if isinstance(value, dict):
        return {
            key: re.sub(r"^[0-9a-f]{64}:", "", item)
            if key == "query" and isinstance(item, str)
            else semantic_result(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [semantic_result(item) for item in value]
        return (
            sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
            if all(isinstance(item, dict) for item in items)
            else items
        )
    return value


def prepare(root, artifacts, snapshot, *, for_publication=False, cold=False):
    started = time.perf_counter()
    if snapshot is not None and snapshot.exists():
        # Snapshot I/O is outside query timing. The trusted IR is acyclic;
        # defer repeated cyclic-GC walks while unpickling millions of records,
        # Freeze this diagnostic snapshot while publishing, or collect once for
        # the reference engine. Restore ordinary GC before measuring queries.
        collecting = gc.isenabled()
        gc.disable()
        try:
            with snapshot.open("rb") as stream:
                index = pickle.load(stream)
            if isinstance(index, IR) and not for_publication:
                index = FactIndex(index)
        finally:
            if collecting:
                if for_publication:
                    gc.freeze()
                else:
                    gc.collect()
                gc.enable()
        return index, {
            "snapshot": str(snapshot),
            "load_seconds": time.perf_counter() - started,
            "snapshot_gc_frozen": for_publication and collecting,
        }
    source = root / ".ken/structural-cache.sqlite"
    local_cache = artifacts / "ir-cache.sqlite"
    if not cold and source.exists() and not local_cache.exists():
        with (
            sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as original,
            sqlite3.connect(local_cache) as copy,
        ):
            original.backup(copy)
    print("Preparing repository graph", flush=True)
    with patch.object(
        service, "IRCache", lambda _path, limit: IRCache(local_cache, limit)
    ):
        graph, analysis = service.build_project(root, cache_mb=500)
    analysis["build_seconds"] = time.perf_counter() - started
    write_json(artifacts / "analysis.json", analysis)
    started = time.perf_counter()
    if for_publication:
        from ken.structural.query_view import normalize_query_graph

        index = normalize_query_graph(graph)
    else:
        index = query_graph(graph)
    del graph
    analysis["normalize_seconds"] = time.perf_counter() - started
    if snapshot is not None:
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with snapshot.open("wb") as stream:
            pickle.dump(index, stream, protocol=5)
    return index, analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--label", default="run")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Build from source without reusing acquisition or query caches",
    )
    parser.add_argument(
        "--patterns", default="", help="Comma-separated GoF ids; default: all 23"
    )
    parser.add_argument(
        "--timeout-ms", type=int, default=0, help="Per-query limit; zero is unlimited"
    )
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--backend", choices=("memory", "sqlite"), default="memory")
    args = parser.parse_args()
    if args.cold and (
        any(
            (args.artifacts / name).exists()
            for name in ("query-index.sqlite", "ir-cache.sqlite")
        )
        or (args.snapshot is not None and args.snapshot.exists())
    ):
        parser.error("--cold requires fresh artifacts and no existing snapshot")
    root = args.repo.resolve()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    store = None
    if args.backend == "sqlite":
        from ken.structural_store import Store
        from ken.structural_store.graph_index import GraphIndex
        from ken.structural_store.graph_projection import publish

        started = time.perf_counter()
        store = Store(args.artifacts / "query-index.sqlite", cache_mb=None)
        opening_seconds = time.perf_counter() - started
        found = store.db.execute(
            "SELECT graph_id FROM k2_graphs JOIN k2_graph_publications USING(graph_id) WHERE ready=1 ORDER BY graph_id DESC LIMIT 1"
        ).fetchone()
        if found:
            index = GraphIndex(store, found[0])
            preparation = {
                "index_hit": True,
                "load_seconds": time.perf_counter() - started,
            }
        else:
            store.close()
            memory, preparation = prepare(
                root,
                args.artifacts,
                args.snapshot,
                for_publication=True,
                cold=args.cold,
            )
            preparation["initial_store_open_seconds"] = opening_seconds
            preparation["relation_counts"] = (
                dict(Counter(f.relation for f in memory.facts))
                if isinstance(memory, IR)
                else {
                    relation: len(rows) for relation, rows in memory.by_relation.items()
                }
            )
            write_json(args.artifacts / "preparation.json", preparation)
            print(
                "PREPARED",
                preparation.get("load_seconds", preparation.get("build_seconds")),
                flush=True,
            )
            store = Store(args.artifacts / "query-index.sqlite", cache_mb=None)
            started = time.perf_counter()
            snapshot_id = store.publish(
                [], expected_parent=store.current, profile="benchmark"
            )
            progress = {}

            def index_progress(table, count):
                elapsed = time.perf_counter() - started
                progress[table] = {"rows": count, "elapsed_seconds": elapsed}
                write_json(args.artifacts / "index-progress.json", progress)
                print("INDEX", table, count, f"{elapsed:.3f}s", flush=True)

            source_ir = memory if isinstance(memory, IR) else memory.ir
            del memory
            graph_id = publish(
                store,
                snapshot_id,
                "benchmark",
                source_ir,
                progress=index_progress,
                consume=True,
                resume=args.snapshot is not None and args.snapshot.exists(),
            )
            preparation["index_write_seconds"] = time.perf_counter() - started
            write_json(args.artifacts / "preparation.json", preparation)
            del source_ir
            if preparation.get("snapshot_gc_frozen"):
                gc.unfreeze()
                gc.collect()
            started = time.perf_counter()
            index = GraphIndex(store, graph_id)
            preparation["syntax_projection_seconds"] = time.perf_counter() - started
        preparation["index_bytes"] = store.allocated_bytes
    else:
        index, preparation = prepare(
            root, args.artifacts, args.snapshot, cold=args.cold
        )
    rules = builtin_rules()
    selected = set(args.patterns.split(",")) if args.patterns else None
    gof = [rule for rule in rules if "gof" in rule.collections]
    if selected and selected - {rule.id for rule in gof}:
        parser.error(
            "unknown GoF ids: "
            + ", ".join(sorted(selected - {rule.id for rule in gof}))
        )
    started = time.perf_counter()
    queries = query_registry(rules)
    report = {
        "repository": str(root),
        "backend": args.backend,
        "entities": len(index.ir.entities),
        "facts": len(index.ir.facts),
        "preparation": preparation,
        "compilation_seconds": time.perf_counter() - started,
        "timeout_ms": args.timeout_ms or None,
        "profiled": args.profile,
        "patterns": {},
    }
    # Allows this same harness to measure a pre-optimization checkout.
    try:
        from ken.structural.relational_resources import ExecutionResources
    except ImportError:
        options = {}
    else:
        options = {"resources": ExecutionResources(index)}
    batch_started = time.perf_counter()
    for rule in gof:
        if selected and rule.id not in selected:
            continue
        print("START", rule.id, flush=True)
        started = time.perf_counter()
        engine = Executor(
            index,
            queries,
            QueryBudget(timeout_ms=args.timeout_ms or None),
            profile=args.profile,
            **options,
        )
        profiler = cProfile.Profile() if args.profile else None
        if profiler:
            profiler.enable()
        try:
            outcome = engine.execute(queries[rule.id])
        finally:
            if hasattr(engine, "close"):
                engine.close()
        if profiler:
            profiler.disable()
        elapsed = time.perf_counter() - started
        prefix = args.artifacts / f"{args.label}-{rule.id}"
        write_json(Path(str(prefix) + ".outcome.json"), outcome)
        # Include evidence and uncertainty, not just the number of findings.
        canonical = json.dumps(
            semantic_result(
                {key: outcome[key] for key in ("matches", "complete", "unknown")}
            ),
            sort_keys=True,
        )
        report["patterns"][rule.id] = {
            "seconds": elapsed,
            "complete": outcome["complete"],
            "matches": len(outcome["matches"]),
            "unknown": outcome["unknown"],
            "result_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "stats": outcome["stats"],
        }
        if profiler:
            profiler.dump_stats(str(Path(str(prefix) + ".prof")))
            write_json(Path(str(prefix) + ".operators.json"), engine.profile)
        report["batch_seconds"] = time.perf_counter() - batch_started
        write_json(args.artifacts / f"{args.label}.json", report)
        print(
            "DONE",
            rule.id,
            round(elapsed, 3),
            "complete",
            outcome["complete"],
            "matches",
            len(outcome["matches"]),
            flush=True,
        )
        del engine, outcome
    if store is not None:
        index.close()
        store.close()


if __name__ == "__main__":
    main()
