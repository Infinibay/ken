"""Diagnose Iterator on an existing, trusted semantic snapshot, without rebuilding.

This does not validate the snapshot against the current source checkout and is
not a time-to-completion benchmark. The query has a five-second budget.
"""

import argparse
import cProfile
import json
import pstats
import time
from contextlib import closing
from pathlib import Path

from ken.kql2.exploration.catalog_index import CatalogIndex
from ken.structural.catalog import detect_patterns
from ken.structural.query import QueryBudget
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-operator-profile", action="store_true")
    args = parser.parse_args()
    if not args.snapshot.is_file():
        parser.error("A pre-existing local snapshot is required")
    with Store(args.snapshot, cache_mb=None) as store:
        graph = store.db.execute(
            "SELECT graph_id FROM k2_graph_publications WHERE ready=1 ORDER BY graph_id DESC LIMIT 1"
        ).fetchone()[0]
        with closing(GraphIndex(store, graph)) as base, closing(CatalogIndex(base)) as index:
            index.profile = not args.no_operator_profile
            counts = []

            def trace(sql):
                if sql.startswith("SELECT count(*)") and len(counts) < 40:
                    counts.append(sql)

            store.db.set_trace_callback(trace)
            profile = cProfile.Profile()
            start = time.monotonic()
            result = profile.runcall(detect_patterns, index, ["iterator"], QueryBudget(timeout_ms=5000))
            elapsed = time.monotonic() - start
            store.db.set_trace_callback(None)
            stats = pstats.Stats(profile)
            functions = [
                {"file": k[0], "line": k[1], "function": k[2],
                 "calls": v[1], "self_seconds": v[2], "cumulative_seconds": v[3]}
                for k, v in stats.stats.items()
            ]
            report = {
                "snapshot": str(args.snapshot.resolve()), "graph": graph,
                "provenance": "Pre-existing semantic snapshot, not reacquired or source-validated",
                "ir_version": base.ir.version, "facts": len(base.ir.facts),
                "entities": len(base.ir.entities), "backend": "exploration",
                "timeout_ms": 5000, "seconds_including_compilation": elapsed,
                "cprofile_enabled": True, "result": result,
                "operator_profile_enabled": index.profile,
                "count_statements_first_40": counts,
                "functions": sorted(functions, key=lambda r: r["cumulative_seconds"], reverse=True)[:35],
            }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    outcome = report["result"]["outcomes"]["iterator"]
    print(json.dumps({k: v for k, v in outcome.items() if k != "stats"}))
    print(json.dumps({k: v for k, v in outcome["stats"].items() if k != "operator_profile"}))


if __name__ == "__main__":
    main()
