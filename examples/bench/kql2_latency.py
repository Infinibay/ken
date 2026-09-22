"""Acceptance gate: all 23 GoF patterns on a prepared index, without result cache.

Run as ``python -m examples.bench.kql2_latency ROOT ARTIFACTS``. Preparation is
reported separately. A timeout, partial result, different evidence, wrong file
count or any measured run at/above the target makes the command fail.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.structural.index_service import project_index
from ken.structural.query import QueryBudget
from ken.structural.service import patterns

from .pattern_search import semantic_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--scope", default=".")
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.warmups < 0 or args.seconds <= 0:
        parser.error("repeats and seconds must be positive; warmups nonnegative")
    root, directory = args.root.resolve(), args.artifacts.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with project_index(root, path=args.scope, database=directory / "patterns.sqlite",
                       source_cache_path=directory / "source-cache.sqlite") as (_, analysis):
        preparation = analysis
    files = []
    for name in preparation["files"]:
        data = (root / name).read_bytes()
        files.append({"path": name, "bytes": len(data), "lines": len(data.splitlines()),
                      "sha256": hashlib.sha256(data).hexdigest()})
    records = []
    for number in range(args.warmups + args.repeats):
        warmup = number < args.warmups
        print(f"Starting {'warmup' if warmup else 'measured run'} {number}", flush=True)
        start = time.monotonic()
        result = patterns(root, path=args.scope, cache_directory=directory,
                          profile=args.profile, use_result_cache=False,
                          budget=QueryBudget(timeout_ms=args.seconds * 1000))
        elapsed = time.monotonic() - start
        comparable = semantic_result({
            "findings": result["findings"], "incomplete": result["incomplete"],
            "outcomes": {name: {k: o[k] for k in ("complete", "unknown")}
                         for name, o in result["outcomes"].items()},
        })
        record = {
            "warmup": warmup, "seconds": elapsed, "complete": result["complete"],
            "patterns": len(result["outcomes"]),
            "index_hit": result["analysis"]["query_index"]["hit"],
            "result_cache": result["analysis"]["query_cache"],
            "semantic_sha256": hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest(),
        }
        record["passed"] = (len(files) == args.files and record["patterns"] == 23
                            and record["index_hit"] and record["complete"]
                            and not record["result_cache"]["enabled"] and elapsed < args.seconds)
        records.append(record)
        (directory / f"latency-{number}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(record), flush=True)
    measured = [r for r in records if not r["warmup"]]
    passed = (all(r["passed"] for r in measured)
              and len({r["semantic_sha256"] for r in measured}) == 1)
    report = {"passed": passed, "target_seconds": args.seconds, "expected_files": args.files,
              "files": files, "preparation": preparation, "runs": records,
              "profile": args.profile,
              "timeout_note": "Per-pattern timeout is diagnostic; acceptance requires the whole batch below the target."}
    (directory / "latency.json").write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
