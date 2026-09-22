"""Subprocess boundary: bound preparation and evaluation as one operation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

from .snapshot import capture, engine_version


def evaluate(request: dict) -> dict:
    from ken.kql2.service import search
    from ken.inspection.imports import dependencies

    root = Path(request["root"])
    before = capture(root, request["path"])
    dependency_before = dependencies(root, before)
    version = engine_version()
    result = search(
        root,
        request["query"],
        path=request["path"],
        libraries=request.get("libraries"),
        max_rows=request["max_rows"],
        max_states=200000,
        timeout_ms=request["timeout_ms"],
        cache_mb=request.get("cache_mb", 100),
    )
    after = capture(root, request["path"])
    captured = dict(result.get("analysis", {}).get("manifest", []))
    inspected = dict(before["manifest"])
    consistent = (
        before == after
        and dependency_before == dependencies(root, after)
        and engine_version() == version
        and all(inspected.get(p) == h for p, h in captured.items())
    )
    if not consistent:
        result.update(complete=False, reason="source_changed_during_check")
    result["check_snapshot"] = before
    result["check_dependencies"] = dependency_before
    result["check_engine"] = version
    return result


def main() -> None:
    try:
        request = json.load(sys.stdin)
        from ken.kql2.request import supervised
        # The checks supervisor already owns this process. Share its deadline
        # rather than spawning a nested worker that could outlive its parent.
        with supervised(request["timeout_ms"]):
            result = evaluate_batch(request) if "queries" in request else evaluate(request)
    except Exception as exc:
        result = {
            "rows": [],
            "complete": False,
            "coverage_complete": False,
            "unknown_candidates": 0,
            "reason": f"{type(exc).__name__}: {exc}",
        }
    json.dump(result, sys.stdout)


def evaluate_batch(request: dict) -> dict:
    """Share acquisition caches and an input receipt, with a single total budget."""
    if request.get("focus") is not None:
        from ken.inspection.exploration import evaluate

        return evaluate(request)
    from ken.kql2.service import search

    root = Path(request["root"])
    before = capture(root, request["path"])
    version = engine_version()
    deadline = time.monotonic() + request["timeout_ms"] / 1000
    selection = None
    if request.get("seeds"):
        from ken.inspection.imports import select

        selection = select(
            root, before, request["seeds"], incoming=request.get("incoming", False)
        )
    results = {}
    for name, query in request["queries"].items():
        try:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            result = search(
                root,
                query,
                path=request["path"],
                timeout_ms=remaining,
                max_rows=request["max_rows"],
                max_states=200000,
                cache_mb=100,
                source_paths=selection["paths"] if selection else None,
            )
        except Exception as exc:
            result = {
                "rows": [],
                "complete": False,
                "coverage_complete": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        results[name] = result
    after = capture(root, request["path"])
    consistent = before == after and engine_version() == version
    for result in results.values():
        captured = dict(result.get("analysis", {}).get("manifest", []))
        if not consistent or any(
            dict(before["manifest"]).get(p) != h for p, h in captured.items()
        ):
            result.update(complete=False, reason="source_changed_during_check")
        result["check_snapshot"] = before
        result["check_engine"] = version
    return {
        "results": results,
        "snapshot": before,
        "engine": version,
        "selection": selection,
    }


if __name__ == "__main__":
    main()
