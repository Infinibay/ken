"""Accumulate bounded query witnesses without hiding partial coverage."""

import json

from .queries import QUERIES


class Observations:
    def __init__(self) -> None:
        self.results: dict[str, dict] = {
            name: {
                "rows": [],
                "entities": {},
                "complete": True,
                "coverage_complete": True,
                "unknown_candidates": 0,
                "results_truncated": False,
                "reason": None,
                "queries": [],
            }
            for name in QUERIES
        }
        self.seen: dict[str, set[str]] = {name: set() for name in QUERIES}
        self.manifest: dict[str, str] = {}
        self.paths: set[str] = set()
        self.invalidated = False

    def add(self, name: str, query: str, result: dict) -> None:
        combined = self.results[name]
        combined["entities"].update(result.get("entities", {}))
        for row in result.get("rows", []):
            key = json.dumps(row, sort_keys=True)
            if key not in self.seen[name]:
                self.seen[name].add(key)
                combined["rows"].append(row)
        for key in ("complete", "coverage_complete"):
            combined[key] &= bool(result.get(key))
        combined["results_truncated"] |= bool(result.get("results_truncated"))
        combined["unknown_candidates"] += result.get("unknown_candidates", 0)
        reasons = filter(None, [combined["reason"], result.get("reason")])
        combined["reason"] = "; ".join(dict.fromkeys(reasons)) or None
        analysis = result.get("analysis", {})
        combined["queries"].append(
            {
                "query": query,
                "source_scope": result.get("source_scope"),
                "analysis": {
                    k: analysis[k]
                    for k in (
                        "parsed_units",
                        "reused_units",
                        "scanned_nodes",
                        "states",
                        "build_ms",
                        "query_ms",
                        "total_ms",
                        "result_cache",
                    )
                    if k in analysis
                },
            }
        )
        for path, fingerprint in analysis.get("manifest", []):
            previous = self.manifest.get(path)
            if previous is not None and previous != fingerprint:
                self.fail("source_changed_during_inspection", discard=True)
            self.manifest[path] = fingerprint
            self.paths.add(path)

    def fail(self, reason: str, *, discard: bool = False) -> None:
        self.invalidated |= discard
        for result in self.results.values():
            result.update(complete=False, reason=reason)
            if discard:
                result["rows"] = []
                result["entities"] = {}

    def batch(self, snapshot: dict, engine: str, selection: dict) -> dict:
        if self.invalidated:
            self.fail("source_changed_during_inspection", discard=True)
        for result in self.results.values():
            result["check_snapshot"] = snapshot
            result["check_engine"] = engine
        return {
            "results": self.results,
            "snapshot": snapshot,
            "engine": engine,
            "selection": selection,
        }
