"""Compare public structural patterns backends on the same source scope."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.structural.query import QueryBudget
from ken.structural.service import patterns

from .pattern_search import semantic_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("--scope", default=".")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout-ms", type=float, default=None)
    parser.add_argument(
        "--backend", choices=("indexed", "exploration", "both"), default="both"
    )
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    records = []
    for repeat in range(args.repeats):
        for backend in (
            ("indexed", "exploration") if args.backend == "both" else (args.backend,)
        ):
            print(f"Starting {backend} repeat {repeat}", flush=True)
            started = time.monotonic()
            result = patterns(
                args.root,
                path=args.scope,
                backend=backend,
                cache_directory=args.artifacts,
                budget=QueryBudget(timeout_ms=args.timeout_ms),
                profile=True,
            )
            elapsed = time.monotonic() - started
            comparable = semantic_result(
                {"findings": result["findings"], "incomplete": result["incomplete"]}
            )
            digest = hashlib.sha256(
                json.dumps(comparable, sort_keys=True).encode()
            ).hexdigest()
            record = {
                "backend": backend,
                "repeat": repeat,
                "seconds": elapsed,
                "complete": result["complete"],
                "findings": len(result["findings"]),
                "sha256": digest,
                "outcomes": result["outcomes"],
                "analysis": result["analysis"],
            }
            records.append(record)
            (args.artifacts / f"{backend}-{repeat}.json").write_text(
                json.dumps(record, indent=2) + "\n"
            )
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in record.items()
                        if k not in {"outcomes", "analysis"}
                    }
                ),
                flush=True,
            )
    (args.artifacts / "comparison.json").write_text(
        json.dumps(records, indent=2) + "\n"
    )
    completed = [record for record in records if record["complete"]]
    if len({record["sha256"] for record in completed}) > 1:
        raise AssertionError("complete backend outcomes differ")


if __name__ == "__main__":
    main()
