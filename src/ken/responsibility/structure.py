"""Corroborate responsibility candidates with one shared program observation."""

from __future__ import annotations

from pathlib import Path

from ken.checks.report import query_view
from ken.inspection.graph import Program, location, qualname, acquisition_view
from ken.inspection.impact import result_uses
from ken.inspection.roles import describe


def enrich(root: Path, result: dict, *, timeout_ms: int = 3000) -> dict:
    if not 1 <= timeout_ms <= 120000:
        raise ValueError("timeout_ms must be 1..120000")
    candidates = result["candidates"]
    if not candidates:
        return result
    paths = sorted({c["path"] for c in candidates})
    scope = result["coverage"]["scope"]
    # A single-file retrieval still needs explicitly imported callees. The
    # retrieval scope and structural acquisition scope are reported separately.
    analysis_scope = "." if (root / scope).is_file() else scope
    program = Program.inspect(
        root,
        path=analysis_scope,
        timeout_ms=timeout_ms,
        seeds=paths,
        focus={"targets": paths, "relation": "outgoing", "depth": 2},
    )
    manifest = dict((program.snapshot or {}).get("manifest", []))
    seeds = []
    for candidate in candidates:
        if manifest.get(candidate["path"]) != candidate["source"]["sha256"]:
            candidate["structure"] = {
                "scope": analysis_scope,
                "reason": "Source changed or structural acquisition incomplete.",
            }
            continue
        selected = [
            key
            for key, node in program.nodes.items()
            if node["path"] == candidate["path"]
            and (
                candidate["kind"] == "module"
                or node["line"] == candidate["line"]
                or candidate["kind"] == "class"
                and qualname(node).startswith(candidate["symbol"] + ".")
            )
        ]
        if not selected:
            continue
        seeds.extend(selected)
        calls = [c for c in program.calls if c["owner"] in selected]
        returned = [
            c
            for c in calls
            if any(
                u["kind"] == "return"
                for t in c["targets"]
                for u in result_uses(program, c, t)
            )
        ]
        evidence = {}
        for kind, observed, coverage_key in (
            ("calls", calls, "calls"),
            ("returned_calls", returned, "usages"),
        ):
            coverage = program.coverage()[coverage_key]
            evidence[kind] = {
                "sites": [location(c["site"]) for c in observed[:5]],
                **coverage,
            }
            if len(observed) > 5:
                evidence[kind]["truncated"] = True
        candidate["structure"] = {
            "scope": analysis_scope,
            "evidence": evidence,
            "observations": {
                name: {
                    "result": query_view(answer),
                    "snapshot": answer.get("check_snapshot"),
                    "engine": answer.get("check_engine"),
                }
                for name, answer in program.observations.items()
            },
            "claim": "Observed calls and returned identities; business roles remain hypotheses.",
        }
    if seeds:
        result["responsibility_map"] = describe(
            program, list(dict.fromkeys(seeds)), depth=2, limit=15
        )
        result["responsibility_map"]["acquisition"] = acquisition_view(
            program.selection
        )
    return result
