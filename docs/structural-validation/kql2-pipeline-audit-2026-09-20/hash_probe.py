"""ABBA experiment: memoize the unchanged structural hash of immutable BODY plans.

Diagnostic monkeypatch only, restored after each run. No engine files are edited.
Run from the Ken checkout with PYTHONPATH=.:src. Reuses an existing SDK cache.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from examples.bench.pattern_search import semantic_result
from ken.kql2.body import BodyPattern
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.service import patterns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scope", default="sdk/typescript")
    args = parser.parse_args()
    # Keep compilation outside the paired timings, including the first baseline.
    query_registry(builtin_rules())
    original = BodyPattern.__hash__
    records = []
    for variant in ("baseline", "memoized_hash", "memoized_hash", "baseline"):
        retained = {}
        calls = misses = 0

        def memoized(pattern):
            nonlocal calls, misses
            calls += 1
            key = id(pattern)
            found = retained.get(key)
            if found is not None:
                assert found[0] is pattern
                return found[1]
            misses += 1
            value = original(pattern)
            if len(retained) >= 4096:
                retained.clear()
            # Hold a strong reference: an id cannot be reused during retention.
            retained[key] = pattern, value
            return value

        context = patch.object(BodyPattern, "__hash__", memoized) if variant == "memoized_hash" else nullcontext()
        start = time.perf_counter()
        with context:
            result = patterns(args.root.resolve(), path=args.scope,
                              backend="exploration", cache_directory=args.cache,
                              profile=True)
        elapsed = time.perf_counter() - start
        comparable = semantic_result({"findings": result["findings"],
                                      "incomplete": result["incomplete"]})
        record = {
            "variant": variant, "seconds": elapsed, "complete": result["complete"],
            "findings": len(result["findings"]),
            "sha256": hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest(),
            "hash_calls": calls, "hash_computations": misses,
            "retained_patterns": len(retained),
            "index_hit": result["analysis"]["query_index"]["hit"],
            "manifest_ms": result["analysis"]["query_index"]["phase_ms"]["manifest"],
            "query_ms": sum(o["stats"]["elapsed_ms"] for o in result["outcomes"].values()),
            "work": {name: {key: outcome["stats"][key] for key in ("states", "rows_examined")}
                     for name, outcome in result["outcomes"].items()},
        }
        assert record["complete"], "An incomplete result cannot demonstrate equivalence"
        if records:
            assert record["sha256"] == records[0]["sha256"]
            assert record["work"] == records[0]["work"]
        records.append(record)
        args.output.write_text(json.dumps(records, indent=2) + "\n")
        print(json.dumps({k: v for k, v in record.items() if k != "work"}), flush=True)


if __name__ == "__main__":
    main()
