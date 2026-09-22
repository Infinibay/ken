"""Trace consumers of selected results and explain a concrete review frontier."""

from __future__ import annotations

from pathlib import PurePosixPath
import re

from .graph import Program, location, qualname
from .result_flow import explain


def is_test(path: str, symbol: str = "") -> bool:
    p = PurePosixPath(path)
    return (
        any(part in {"test", "tests", "__tests__"} for part in p.parts)
        or p.name.startswith("test_")
        or ".test." in p.name
        or ".spec." in p.name
        or symbol.split(".")[-1].startswith("test_")
    )


def span(value: str) -> tuple[str, str] | None:
    match = re.search(r"(?:@|::op:)(\d+):(\d+)(?::call)?$", value)
    return (match[1], match[2]) if match else None


def result_uses(program: Program, call: dict, target: str) -> list[dict]:
    occurrence = span(call["site"]["local_id"])
    return [
        item["usage"]
        for item in program.uses
        if item["owner"] == call["owner"]
        and item["target"] == target
        and occurrence is not None
        and span(item["site"]) == occurrence
    ]


def analyze(
    program: Program, seeds: list[str], *, depth: int = 2, limit: int = 20
) -> dict:
    frontier, visited = set(seeds), set(seeds)
    consumers, tests, unresolved = [], [], []
    seen_calls = set()
    for hop in range(1, depth + 1):
        following = set()
        for call in program.calls:
            affected = frontier & set(call["targets"])
            if not affected:
                continue
            site_id = call["site"]["local_id"]
            if site_id in seen_calls:
                continue
            seen_calls.add(site_id)
            owner = program.nodes.get(call["owner"])
            if owner is None:
                continue
            uses = [
                u for target in affected for u in result_uses(program, call, target)
            ]
            item = {
                "caller": location(owner) | {"symbol": qualname(owner)},
                "call": location(call["site"]),
                "resolution": call["resolution"],
                "result_uses": [
                    {
                        k: u[k]
                        for k in ("kind", "path", "line", "position")
                        if u.get(k) is not None
                    }
                    for u in uses
                ],
                "hops": hop,
                "result_flow": explain(program, uses, resolved=call["resolution"] == "resolved", hop=hop, depth=depth),
                "via": [
                    location(program.nodes[t])
                    for t in sorted(affected)
                    if t in program.nodes
                ],
            }
            if not uses:
                item["usage_status"] = "unknown"
            consumers.append(item)
            if is_test(owner["path"], qualname(owner)):
                tests.append(item)
            # Only witnessed returned identity propagates this result into the
            # caller's return; transformed values are never silently equated.
            if call["resolution"] == "resolved" and any(
                u["kind"] == "return" for u in uses
            ):
                following.add(call["owner"])
        frontier = following - visited
        visited.update(following)
    seed_names = {program.nodes[s]["name"] for s in seeds if s in program.nodes}
    for call in program.calls:
        if call["resolution"] != "resolved" and call["site"]["name"] in seed_names:
            unresolved.append(
                location(call["site"])
                | {
                    "resolution": call["resolution"],
                    "claim": "Spelling match only; not an established dependency.",
                }
            )
    return {
        "scope": program.scope,
        "targets": [location(program.nodes[s]) for s in seeds],
        "consumers": consumers[:limit],
        "tests": tests[:limit],
        "unresolved_candidates": unresolved[:limit],
        "truncated": max(len(consumers), len(tests), len(unresolved)) > limit,
        "depth": depth,
        "coverage": program.coverage(),
        "claim": "Observed result consumers and return propagation. Test links show use, not assertion coverage; empty uses are not proof of discard.",
    }
