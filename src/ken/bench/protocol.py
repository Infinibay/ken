"""Dataset isolation, frozen inputs and one-use acceptance receipts."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from ken.bench.dataset import Record, valid_path


def validate_partitions(development: Iterable[Record], reserve: Iterable[Record]) -> None:
    development, reserve = list(development), list(reserve)
    for field, label in (("repo_id", "repository"), ("behavior_group", "behavior")):
        if {c[field] for c in development} & {c[field] for c in reserve}:
            raise ValueError(f"{label} leakage between development and acceptance")
    normalize = lambda q: " ".join(q.casefold().split())
    if {normalize(c["query"]) for c in development} & {normalize(c["query"]) for c in reserve}:
        raise ValueError("query leakage between development and acceptance")


def acceptance_failures(cases: Iterable[Record]) -> list[str]:
    cases = list(cases)
    positive = [c for c in cases if c["answerable"]]
    failures = []
    if len(positive) != 300:
        failures.append(f"acceptance requires 300 positives, received {len(positive)}")
    repos = Counter(c["repo_id"] for c in positive)
    if len(repos) != 12 or set(repos.values()) != {25}:
        failures.append("acceptance requires 12 repositories with 25 positives each")
    languages = Counter(c["language"] for c in positive)
    if languages != {"en": 180, "es": 120}:
        failures.append("acceptance requires 180 EN and 120 ES positives")
    purposes = Counter(c["purpose"] for c in positive)
    if (purposes["implementation"] != 210 or purposes["identity"] != 45
            or sum(purposes[p] for p in ("usage", "tests", "documentation")) != 45):
        failures.append("acceptance purpose quotas must be 210/45/45")
    if len(cases) - len(positive) < 60:
        failures.append("acceptance requires at least 60 separate negatives")
    queries = [" ".join(c["query"].casefold().split()) for c in cases]
    if len(set(queries)) != len(queries):
        failures.append("duplicate query in acceptance")
    for repo in {c["repo_id"] for c in cases}:
        if len({c["repo_commit"] for c in cases if c["repo_id"] == repo}) != 1:
            failures.append(f"mixed source commits for {repo}")
    for case in positive:
        for alternative in case["alternatives"]:
            lines = {line for span in alternative["anchors"]
                     for line in range(span["start_line"], span["end_line"] + 1)}
            if len(lines) > 40:
                failures.append(f"reference exceeds visible line budget: {case['id']}")
    return failures


def verify_files(root: Path, expected: Mapping[str, str]) -> None:
    for path, digest in expected.items():
        source = (root / path).resolve()
        if not valid_path(path) or not source.is_relative_to(root.resolve()):
            raise ValueError("invalid frozen artifact path")
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f"frozen artifact mismatch: {path}")


def claim_reserve(registry: Path, *, dataset_sha256: str, engine_sha256: str,
                  profile_sha256: str) -> None:
    """Claim before execution. A crash also consumes the attempt; it cannot erase exposure."""
    for digest in (dataset_sha256, engine_sha256, profile_sha256):
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("SHA256 receipt required")
    registry.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(registry) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS attempts (dataset_sha256 TEXT PRIMARY KEY, "
                     "engine_sha256 TEXT, profile_sha256 TEXT, created_at TEXT)")
        try:
            conn.execute("INSERT INTO attempts VALUES (?,?,?,?)",
                         (dataset_sha256, engine_sha256, profile_sha256,
                          datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("reserve has already been consumed; curate a new independent reserve") from exc
