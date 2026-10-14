"""Diagnose candidate identity and source-anchor coverage, keeping planned totals."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import _identity

from replay import load_pools


def covered(passages, anchors):
    visible = {line for p in passages for line in range(p.span.start_line, p.span.end_line + 1)}
    return all(set(range(a["start_line"], a["end_line"] + 1)) <= visible for a in anchors)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pool", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent / "datasets"
    dataset = load_dataset(base / "development.jsonl")
    cases = {c["id"]: c for c in dataset}
    roots = {r: Path(p) for r, p in json.loads((base / "roots-development.json").read_text()).items()}
    pools = load_pools(args.pool, cases)
    rows = []
    for case in dataset:
        candidates = pools.get(case["id"], [])
        identity, evidence = False, False
        for candidate in candidates:
            record = {"path": candidate.entity.path, "entity": candidate.entity.to_dict()}
            for alternative in case["alternatives"]:
                if not _identity(record, alternative):
                    continue
                source = roots[case["repo_id"]] / alternative["path"]
                if hashlib.sha256(source.read_bytes()).hexdigest() != alternative["source_hash"]:
                    raise ValueError("candidate audit source no longer matches frozen reference")
                anchors = covered(candidate.passages, alternative["anchors"])
                identity |= alternative.get("entity") is not None or anchors
                evidence |= anchors
        rows.append({"id": case["id"], "observed": case["id"] in pools,
                     "identity_or_fragment": identity, "all_anchors": evidence})
    observed = sum(r["observed"] for r in rows)
    report = {"status": "complete" if observed == len(rows) else "incomplete",
        "planned": len(rows), "observed": observed, "missing_count_as_zero": True,
        "identity_or_fragment": sum(r["identity_or_fragment"] for r in rows),
        "all_anchors": sum(r["all_anchors"] for r in rows), "rows": rows,
        "dataset_sha256": dataset.sha256,
        "pool_sha256": hashlib.sha256((args.pool / "candidates.jsonl").read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}))


if __name__ == "__main__":
    main()
