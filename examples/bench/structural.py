"""Reproducible structural analysis benchmark; no services or model downloads.

Run: uv run python examples/bench/structural.py --files 300
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from ken.structural.service import build_project
from ken.structural.catalog import detect_patterns
from ken.structural.model import FactIndex
from ken.structural.query import QueryBudget, evaluate_pattern

SOURCE = '''class Assembly:
    def size(self, value):
        self.width = value
        return self
    def color(self, value):
        self.tint = value
        return self
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=300)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ken-structural-bench-") as directory:
        root = Path(directory)
        for i in range(args.files):
            (root / f"unit_{i:05}.py").write_text(SOURCE)
        graph, cold = build_project(root, max_files=max(2000, args.files))
        _, warm = build_project(root, max_files=max(2000, args.files))
        started = time.perf_counter()
        index = FactIndex(graph)
        index_ms = (time.perf_counter() - started) * 1000
        query = 'method(name: /^size$/) as $method { has_parameter(pos: 0) as $arg; }'
        evaluate_pattern(index, query, QueryBudget(max_matches=args.files + 1))
        durations = []
        for _ in range(5):
            result = evaluate_pattern(index, query, QueryBudget(max_matches=args.files + 1))
            durations.append(result.stats["elapsed_ms"])
        assert result.complete and len(result.matches) == args.files
        from ken.structural.kenql import Engine, parse, query_graph
        modern_index = query_graph(graph)
        named = parse('query sized { method(name: "size") as $m; emit method=$m; }')
        consumer = parse('query use_size { match "team.sized"(method:$m); emit $m; }')
        modern = Engine(modern_index, {"team.sized": named}, QueryBudget(max_matches=args.files + 1)).execute(consumer)
        assert modern["complete"] and len(modern["matches"]) == args.files
        started = time.perf_counter()
        catalog = detect_patterns(index, budget=QueryBudget(max_matches=args.files + 1))
        catalog_ms = (time.perf_counter() - started) * 1000
        print(json.dumps({"files": args.files, "entities": len(graph.entities), "facts": len(graph.facts),
                          "operations": len(graph.operations), "cold_ms": cold["elapsed_ms"],
                          "warm_ms": warm["elapsed_ms"], "index_ms": round(index_ms, 3),
                          "query_median_ms": statistics.median(durations), "query_matches": len(result.matches),
                          "named_query_ms": modern["stats"]["elapsed_ms"], "named_query_matches": len(modern["matches"]),
                          "catalog_ms": round(catalog_ms, 3), "catalog_complete": catalog["complete"],
                          "cache": warm["cache"]}, indent=2))


if __name__ == "__main__":
    main()
