"""Strict top-1 scoring: identity AND faithful, visible implementation evidence."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ken.bench.dataset import Record, valid_path, validate_case, validate_span

MAX_CHARS = 12000
MAX_LINES = 40
MIN_TOP1 = 0.90


def request_for_case(case: Record) -> Record:
    """Only public inputs enter retrieval; judgments are never query hints."""
    return {"query": case["query"], "purpose": "auto", "target": "symbol",
            "limit": 10, "max_chars": MAX_CHARS}


def _metric(hits: int, total: int) -> Record:
    return {"hits": hits, "total": total, "rate": hits / total if total else 0.0}


def _identity(result: Record, alternative: Record) -> bool:
    if result.get("path") != alternative["path"]:
        return False
    expected = alternative.get("entity")
    actual = result.get("entity")
    return expected is None or (
        isinstance(actual, dict) and all(actual.get(k) == expected.get(k)
        for k in ("kind", "qualname", "owner", "definition_ordinal"))
    )


def _visible_lines(result: Record, root: Path) -> set[int]:
    path = result.get("path")
    if not isinstance(path, str) or not valid_path(path):
        raise ValueError("invalid response path")
    source_path = (root / path).resolve()
    if not source_path.is_relative_to(root.resolve()):
        raise ValueError("response escapes project root")
    source = source_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != result.get("source_hash"):
        raise ValueError("stale or missing response source hash")
    lines = source.decode("utf-8").splitlines()
    visible: set[int] = set()
    evidence = result.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("missing evidence")
    shown = 0
    for fragment in evidence:
        validate_span(fragment)
        start, end = fragment["start_line"], fragment["end_line"]
        if end > len(lines) or fragment.get("stale"):
            raise ValueError("evidence outside current source")
        if fragment.get("content") != "\n".join(lines[start - 1:end]):
            raise ValueError("evidence content does not match its source span")
        shown += end - start + 1
        visible.update(range(start, end + 1))
    if shown > MAX_LINES:
        raise ValueError("visible evidence exceeds line budget")
    return visible


def _score(case: Record, response: Record | None, root: Path) -> tuple[bool, bool, str]:
    if response is None:
        return False, False, "missing_response"
    if response.get("error") or response.get("ok") is False:
        return False, False, "error"
    payload = {key: value for key, value in response.items() if key != "id"}
    if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) > MAX_CHARS:
        return False, False, "output_budget"
    results = response.get("results")
    if not isinstance(results, list) or not results:
        return False, False, "empty"
    if len(results) > 10 or not isinstance(results[0], dict):
        return False, False, "invalid_results"
    first = results[0]
    alternatives = [alt for alt in case["alternatives"] if _identity(first, alt)]
    if not alternatives:
        return False, False, "wrong_identity"
    try:
        visible = _visible_lines(first, root)
    except (ValueError, OSError, UnicodeError, TypeError, KeyError):
        return True, False, "invalid_evidence"
    for alt in alternatives:
        if alt["source_hash"] == first.get("source_hash") and all(
            set(range(anchor["start_line"], anchor["end_line"] + 1)) <= visible
            for anchor in alt["anchors"]
        ):
            return True, True, "hit"
    return True, False, "missing_anchor"


def evaluate(cases: Iterable[Record], responses: Iterable[Record], *,
             roots: Mapping[str, Path]) -> Record:
    judgments = [validate_case(case) for case in cases]
    ids = [case["id"] for case in judgments]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case id")
    by_id: dict[str, Record] = {}
    for response_record in responses:
        if not isinstance(response_record, dict):
            raise ValueError("response must be an object")
        rid = response_record.get("id")
        if not isinstance(rid, str):
            raise ValueError("response id must be a string")
        if rid in by_id:
            raise ValueError(f"duplicate response id: {rid}")
        if rid not in ids:
            raise ValueError(f"unknown response id: {rid}")
        by_id[rid] = response_record
    rows: list[Record] = []
    strata: dict[str, list[Record]] = defaultdict(list)
    negatives: list[Record] = []
    for case in judgments:
        root = roots[case["repo_id"]]
        # Validate reference bytes before grading; corrupt gold is not a search miss.
        for alt in case["alternatives"]:
            source_path = (root / alt["path"]).resolve()
            if not source_path.is_relative_to(root.resolve()):
                raise ValueError("gold path escapes project")
            source = source_path.read_bytes()
            if hashlib.sha256(source).hexdigest() != alt["source_hash"]:
                raise ValueError(f"reference snapshot mismatch: {case['id']}")
            if any(a["end_line"] > len(source.decode("utf-8").splitlines()) for a in alt["anchors"]):
                raise ValueError(f"reference span outside source: {case['id']}")
        response = by_id.get(case["id"])
        if not case["answerable"]:
            negatives.append({"id": case["id"], "returned_results": bool(
                response and response.get("results"))})
            continue
        identity, hit, reason = _score(case, response, root)
        row = {"id": case["id"], "identity_hit": identity, "strict_hit": hit, "reason": reason}
        rows.append(row)
        for group in ("all", f"repo:{case['repo_id']}", f"language:{case['language']}",
                      f"purpose:{case['purpose']}"):
            strata[group].append(row)
    metrics = {key: _metric(sum(r["strict_hit"] for r in group), len(group))
               for key, group in strata.items()}
    repos = [m["rate"] for key, m in metrics.items() if key.startswith("repo:")]
    return {
        "schema_version": 2,
        "strict_top1": metrics.get("all", _metric(0, 0)),
        "identity_top1": _metric(sum(r["identity_hit"] for r in rows), len(rows)),
        "macro_repo_top1": sum(repos) / len(repos) if repos else 0.0,
        "strata": metrics, "rows": rows, "negatives": negatives,
        "missing_response_ids": [rid for rid in ids if rid not in by_id],
    }


def check_gate(report: Record, policy: Record | None = None) -> list[str]:
    """The approved floor is not configurable downward, even through policy files."""
    threshold = (policy or {}).get("min_top1", MIN_TOP1)
    if (type(threshold) not in (int, float) or not math.isfinite(threshold)
            or not MIN_TOP1 <= threshold <= 1):
        raise ValueError("top1 floor must be finite, >=0.90 and <=1")
    failures = []
    for key in ("all", "language:en", "language:es", "purpose:implementation"):
        metric = report["strata"].get(key, _metric(0, 0))
        if not metric["total"] or metric["rate"] < threshold:
            failures.append(f"strict_top1 {key}: {metric['hits']}/{metric['total']} < {threshold}")
    if report["macro_repo_top1"] < threshold:
        failures.append(f"strict_top1 macro_repo: {report['macro_repo_top1']} < {threshold}")
    return failures


def main(dataset_path: Path, *, roots_path: Path, responses_path: Path,
         policy_path: Path | None = None) -> int:
    """Score frozen responses; live execution is a separate, traceable producer."""
    from ken.bench.dataset import load_dataset
    dataset = load_dataset(dataset_path)
    roots = {key: Path(path) for key, path in json.loads(roots_path.read_text()).items()}
    responses = [json.loads(line) for line in responses_path.read_text().splitlines() if line.strip()]
    report = evaluate(dataset, responses, roots=roots)
    policy = json.loads(policy_path.read_text()) if policy_path else None
    report["dataset_sha256"] = dataset.sha256
    if policy_path:
        from ken.bench.protocol import acceptance_failures
        report["failures"] = check_gate(report, policy) + acceptance_failures(dataset)
    else:
        report["failures"] = []
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return int(bool(report["failures"]))
