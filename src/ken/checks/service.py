"""Coordinate selection, bounded evaluation, comparison and receipt publication."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from . import execution
from .model import Rule, judgment, relative
from .report import compare as comparison, run_view
from .rules import validated
from .selection import affected, changed_paths
from .snapshot import engine_version
from .store import Store


def latest(store: Store) -> dict | None:
    directory = store.base / "runs"
    if not directory.exists():
        return None
    files = sorted(
        directory.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    )
    return store.read("runs", files[0].stem) if files else None


def check(
    root: Path,
    *,
    rules: list[str] | None = None,
    path: str = ".",
    scope: str = "project",
    compare: str = "",
    run_id: str = "",
    timeout_ms: int = 10000,
    max_rows: int = 100,
    full: bool = False,
    automatic: bool = False,
    touched: list[str] | None = None,
) -> dict:
    if not 1 <= timeout_ms <= 120000 or not 1 <= max_rows <= 1000:
        raise ValueError("invalid execution budget")
    deadline = time.monotonic() + timeout_ms / 1000
    path = relative(path)
    if scope not in {"project", "changes"}:
        raise ValueError("scope must be project or changes")
    store = Store(root)
    if run_id:
        return run_view(store.read("runs", run_id), full=full)
    records = store.rules()
    known = {record["definition"]["id"] for record in records}
    if rules is not None and (not rules or len(rules) > 16 or set(rules) - known):
        raise ValueError("rules must name 1..16 registered check rules")
    version = engine_version()
    unvalidated = [
        r
        for r in records
        if rules is None
        and r["enabled"]
        and not validated(r, version)
        and (not automatic or r["automatic"])
    ]
    selected = [
        record
        for record in records
        if (
            record["definition"]["id"] in rules
            if rules is not None
            else record["enabled"] and validated(record, version)
        )
        and (
            not automatic
            or record["automatic"]
            and validated(record, version)
            and record["enabled"]
        )
    ]
    changed = (
        touched
        if touched is not None
        else changed_paths(root)
        if scope == "changes"
        else None
    )
    selection_evidence: dict = {}
    if path != ".":
        ids, selection_evidence = affected(
            root,
            selected + unvalidated,
            [path],
            seconds=min(1.0, timeout_ms / 4000),
            include_deleted=False,
        )
        selected = [r for r in selected if r["definition"]["id"] in ids]
        unvalidated = [r for r in unvalidated if r["definition"]["id"] in ids]
    if changed is not None:
        ids, selection_evidence = affected(
            root, selected + unvalidated, changed, seconds=min(1.0, timeout_ms / 4000)
        )
        selected = [r for r in selected if r["definition"]["id"] in ids]
        unvalidated = [r for r in unvalidated if r["definition"]["id"] in ids]
    if len(selected) > 16:
        raise ValueError("select at most 16 rules per check")
    baseline = (
        latest(store)
        if compare == "last"
        else store.read("runs", compare)
        if compare
        else None
    )
    observations = []
    for record in selected:
        rule = Rule.read(record["definition"])
        remaining = max(1, int((deadline - time.monotonic()) * 1000))
        result = execution.run(
            root,
            rule.query,
            path=rule.path,
            libraries=rule.libraries,
            timeout_ms=remaining,
            max_rows=max_rows,
        )
        try:
            current_revision = Rule.read(
                store.read("rules", rule.id)["definition"]
            ).revision
        except (OSError, ValueError, KeyError):
            current_revision = None
        if current_revision != rule.revision:
            result.update(complete=False, reason="rule_changed_during_check")
        if result.get("check_engine") not in (None, version):
            result.update(complete=False, reason="engine_changed_after_rule_selection")
        observations.append(
            {
                "rule": rule.id,
                "description": rule.description,
                "revision": rule.revision,
                "path": rule.path,
                "query": rule.query,
                "libraries": rule.libraries,
                "expectation": rule.expectation,
                "status": judgment(result, rule.expectation),
                "engine": result.get("check_engine", version),
                "result": result,
            }
        )
    statuses = {item["status"] for item in observations}
    if unvalidated:
        statuses.add("unknown")
    status = (
        "not_applicable"
        if not statuses
        else "fail"
        if "fail" in statuses
        else "unknown"
        if "unknown" in statuses
        else "pass"
    )
    receipt: dict[str, Any] = {
        "version": 1,
        "run_id": uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "selection": path,
        "status": status,
        "checks": observations,
        "selection_evidence": selection_evidence,
    }
    if unvalidated:
        receipt["skipped_rules"] = [
            {
                "rule": r["definition"]["id"],
                "reason": "rule or engine changed; validate again",
            }
            for r in unvalidated
        ]
    if baseline:
        receipt["comparison"] = comparison(baseline, receipt)
    if observations or unvalidated:
        store.write("runs", receipt["run_id"], receipt)
    return run_view(receipt, full=full)
