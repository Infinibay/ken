"""Expose existing rules and receipts to search, impact and memory callers."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from . import execution
from .model import Rule, relative
from .report import observation_view, query_view
from .rules import view
from .selection import affected, overlaps
from .snapshot import capture, engine_version
from .store import Store


def search(
    root: Path,
    ids: list[str],
    *,
    path: str = ".",
    timeout_ms: int = 10000,
    max_rows: int = 100,
    full: bool = False,
) -> dict:
    store = Store(root)
    deadline = time.monotonic() + timeout_ms / 1000
    results: list[dict[str, Any]] = []
    for rule_id in dict.fromkeys(ids):
        rule = Rule.read(store.read("rules", rule_id)["definition"])
        if not overlaps(rule.path, path):
            continue
        result = execution.run(
            root,
            rule.query,
            path=rule.path,
            libraries=rule.libraries,
            timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
            max_rows=max_rows,
        )
        results.append(
            {
                "rule": rule_id,
                "path": rule.path,
                "result": query_view(result, full=full),
            }
        )
    return {
        "results": results,
        "complete": all(r["result"].get("complete") for r in results),
    }


def freshness(root: Path, receipt: dict, *, seconds: float = 0.5) -> dict:
    store = Store(root)
    issues = []
    states = []
    version = engine_version()
    started = time.monotonic()
    snapshots: dict[str, dict] = {}
    checks = []
    for check in receipt["checks"]:
        detail = {
            "rule": check["rule"],
            "path": check["path"],
            "status": check["status"],
        }
        checks.append(detail)
        try:
            rule = Rule.read(store.read("rules", check["rule"])["definition"])
            if rule.revision != check["revision"] or version != check["engine"]:
                states.append("stale")
                issues.append(f"{rule.id}: rule or engine changed")
                detail["validity"] = "stale"
                continue
            scope = check["path"]
            if scope not in snapshots:
                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError("check freshness budget exhausted")
                snapshots[scope] = capture(root, scope, seconds=remaining)
            before = check["result"].get("check_snapshot")
            if before is None:
                raise ValueError("receipt has no source snapshot")
            state = "unchanged" if snapshots[scope] == before else "stale"
            old_files = dict(before.get("manifest", []))
            new_files = dict(snapshots[scope].get("manifest", []))
            changed_files = sorted(
                p
                for p in old_files.keys() | new_files.keys()
                if old_files.get(p) != new_files.get(p)
            )
            if state == "unchanged" and "check_dependencies" in check["result"]:
                from ken.inspection.imports import dependencies

                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError("dependency freshness budget exhausted")
                live_deps = dependencies(root, snapshots[scope], seconds=remaining)
                old_deps = check["result"]["check_dependencies"]
                if live_deps != old_deps:
                    state = "stale"
                    old = dict(old_deps.get("manifest", []))
                    new = dict(live_deps.get("manifest", []))
                    changed_files.extend(
                        p for p in old.keys() | new.keys() if old.get(p) != new.get(p)
                    )
            detail.update(validity=state, changed_files=sorted(set(changed_files)))
            states.append(state)
            if state != "unchanged":
                issues.append(f"{rule.id}: source inventory or contents changed")
        except (ValueError, OSError, KeyError) as exc:
            states.append("unknown")
            issues.append(f"{check['rule']}: {exc}")
            detail.update(validity="unknown", reason=str(exc))
    state = (
        "stale"
        if "stale" in states
        else "unknown"
        if "unknown" in states or not states
        else "unchanged"
    )
    return {
        "state": state,
        "issues": issues,
        "checks": checks,
        "scope": "Recorded check inputs; the memory's prose is not independently proved.",
    }


def related(root: Path, path: str, *, limit: int = 10) -> dict:
    path = relative(path)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    store = Store(root)
    records = store.rules()
    selected, selection_evidence = affected(root, records, [path])
    records = [r for r in records if r["definition"]["id"] in selected]
    if not records:
        return {"rules": [], "checks": []}
    version = engine_version()
    directory = store.base / "runs"
    paths = (
        sorted(
            directory.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
        )
        if directory.exists()
        else []
    )
    checks = []
    seen = set()
    for source in paths[:100]:
        run = store.read("runs", source.stem)
        for observation in run["checks"]:
            if observation["rule"] in seen or observation["rule"] not in selected:
                continue
            seen.add(observation["rule"])
            checks.append(
                observation_view(observation)
                | {
                    "run_id": run["run_id"],
                    "validity": freshness(root, run | {"checks": [observation]}),
                }
            )
            if len(checks) >= limit:
                break
        if len(checks) >= limit:
            break
    return {
        "rules": [view(r, version=version) for r in records[:limit]],
        "checks": checks,
        "omitted_rules": max(0, len(records) - limit),
        "selection_evidence": selection_evidence,
    }


def justification(root: Path, run_id: str, data: dict | None = None) -> dict:
    store = Store(root)
    receipt = store.read("runs", run_id)
    state = freshness(root, receipt, seconds=2.0)
    if state["state"] != "unchanged":
        raise ValueError(
            "check inputs changed or cannot be verified; rerun ken_check before recording"
        )
    value = dict(data or {})
    value.setdefault("kind", "observation")
    value.setdefault(
        "rationale",
        "This note references the selected KQL2 source-contract checks; retain their scope and uncertainty.",
    )
    value.setdefault(
        "recheck",
        "ken_check with the referenced rules; update this note only after reviewing the new result.",
    )
    value["check_runs"] = list(dict.fromkeys([*value.get("check_runs", []), run_id]))
    return value
