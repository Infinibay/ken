"""Present only decision-relevant evidence, or retain the full diagnostic record."""

from __future__ import annotations

import re
from typing import Any

from .reasoners import overlap, terms


def render(result: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    """Change presentation only: preserve ranking, uncertainty and counterevidence."""
    if full:
        return result
    out: dict[str, Any] = {
        "status": result["status"],
        "score_kind": "heuristic_not_probability",
        "candidates": [_candidate(c, result["question"]) for c in result["candidates"]],
    }
    if result["counterevidence"]:
        out["counterevidence"] = [
            _candidate(c, result["question"]) for c in result["counterevidence"]
        ]
    if result["status"] == "unknown":
        out["reason"] = (
            "Insufficient evidence in the inspected indexed code; not proof of absence."
        )
    issues = result["coverage"]["issues"]
    if issues:
        out["uninspected_candidates"] = len(issues)
    if result.get("responsibility_map"):
        out["responsibility_map"] = result["responsibility_map"]
    return out


def _candidate(candidate: dict[str, Any], question: str) -> dict[str, Any]:
    out = {key: candidate[key] for key in ("symbol", "kind", "path", "line")}
    if out["symbol"] == out["path"] and out["kind"] == "module":
        del out["symbol"]
    out["score"] = candidate["confidence"]["score"]
    documentation = candidate["documentation"]
    if documentation:
        # The most relevant sentence is more useful than a generic first line
        # such as "Public entry point". This selects a quote, not a new claim.
        fragments = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", documentation)
            if s.strip()
        ]
        query = terms(candidate["matched_formulation"])
        if fragments:
            quote = max(fragments, key=lambda s: overlap(query, s))
            out["evidence"] = quote if len(quote) <= 200 else quote[:199] + "…"
    elif candidate["evidence"]:
        out["evidence"] = candidate["evidence"][0]["explanation"]
    if candidate["matched_formulation"] != question:
        out["assumed_formulation"] = candidate["matched_formulation"]
    caveats = []
    for item in candidate["evidence"]:
        if item["direction"] != "supports":
            caveats.append(item["explanation"])
        if item["assumption"] and (
            item["direction"] != "supports"
            or item["reasoner"] not in {"documentation", "name"}
        ):
            caveats.append(item["assumption"])
    if caveats:
        out["caveats"] = list(dict.fromkeys(caveats))
    if candidate.get("structure"):
        out["structure"] = {k: v for k, v in candidate["structure"].items() if k != "observations"}
    return out
