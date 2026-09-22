"""Compact views preserve epistemic status; full views retain source receipts."""

from __future__ import annotations

from typing import Any

from .model import digest


def locations(value: Any) -> list[dict]:
    found: list[dict] = []

    def visit(item):
        if isinstance(item, dict):
            if isinstance(item.get("path"), str) and isinstance(item.get("line"), int):
                found.append(
                    {k: item[k] for k in ("path", "line", "name", "kind") if k in item}
                )
            else:
                for child in item.values():
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return list({digest(item): item for item in found}.values())


def query_view(result: dict, *, full: bool = False) -> dict:
    if full:
        return result
    out = {
        k: result[k]
        for k in (
            "language",
            "query",
            "columns",
            "rows",
            "complete",
            "coverage_complete",
            "unknown_candidates",
            "results_truncated",
            "source_scope",
            "diagnostics",
        )
        if k in result
    }
    if result.get("reason"):
        out["reason"] = result["reason"]
    if result.get("optional_evidence"):
        evidence = result["optional_evidence"]
        if all(isinstance(item, dict) and "row" in item and "evidence" in item for item in evidence):
            # Graph execution includes a complete proof tree for every row.
            # Keep source anchors in compact output; --full retains each edge.
            anchors = []
            for item in evidence:
                sources: set[str] = set()
                relations: set[str] = set()
                optional = 0
                pending = [item["evidence"]]
                while pending:
                    current = pending.pop()
                    if isinstance(current, dict):
                        sources.update(s for s in current.get("source", []) if isinstance(s, str))
                        if isinstance(current.get("relation"), str):
                            relations.add(current["relation"])
                        optional += int("optional" in current)
                        pending.extend(current.values())
                    elif isinstance(current, list):
                        pending.extend(current)
                anchors.append({"row": item["row"], "sources": sorted(sources),
                                "relations": sorted(relations),
                                **({"optional_witnesses": optional} if optional else {})})
            out["evidence"] = anchors
        else:
            out["optional_evidence"] = evidence
    analysis = result.get("analysis", {})
    timing = {key: round(analysis[key], 1) for key in
              ("total_ms", "timeout_ms", "compile_ms", "build_ms", "query_ms")
              if isinstance(analysis.get(key), (int, float))}
    if timing:
        out["timing"] = timing
    if analysis.get("stopped_phase"):
        out["stopped_phase"] = analysis["stopped_phase"]
        out["preparation"] = {key: analysis[key] for key in
                              ("parsed_units", "reused_units", "current_path") if key in analysis}
    return out


def observation_view(observation: dict) -> dict:
    result = observation["result"]
    out = {
        k: observation[k]
        for k in ("rule", "description", "path", "expectation", "status")
    }
    out.update(
        matches=len(result.get("rows", [])),
        locations=locations(result.get("rows", []))[:12],
        complete=bool(result.get("complete")),
        coverage_complete=bool(result.get("coverage_complete")),
        unknown_candidates=result.get("unknown_candidates", 0),
    )
    if result.get("reason"):
        out["reason"] = result["reason"]
    if result.get("diagnostics"):
        out["diagnostics"] = result["diagnostics"]
    if result.get("results_truncated"):
        out["results_truncated"] = True
    if result.get("rows") and not out["locations"]:
        out["witnesses"] = result["rows"][:3]
    return out


def run_view(receipt: dict, *, full: bool = False) -> dict:
    if full:
        return receipt
    out = {
        k: receipt[k] for k in ("run_id", "status", "scope", "selection", "created_at")
    }
    out["checks"] = [observation_view(o) for o in receipt["checks"]]
    if receipt.get("comparison"):
        out["comparison"] = receipt["comparison"]
    if receipt.get("skipped_rules"):
        out["skipped_rules"] = receipt["skipped_rules"]
    if receipt.get("selection_evidence"):
        out["selection_evidence"] = receipt["selection_evidence"]
    out["claim"] = (
        "Selected source contracts only; not proof of runtime behavior or absence of all bugs."
    )
    return out


def compare(before: dict, after: dict) -> dict:
    previous = {item["rule"]: item for item in before["checks"]}
    changes = []
    for item in after["checks"]:
        old = previous.get(item["rule"])
        comparable = old is not None and all(
            old.get(k) == item.get(k) for k in ("revision", "path", "engine")
        )
        status = "not_comparable"
        if comparable:
            assert old is not None
            if "unknown" in {old["status"], item["status"]}:
                status = "inconclusive"
            elif old["status"] == item["status"]:
                status = "unchanged"
            else:
                status = "regression" if item["status"] == "fail" else "resolved"
        changes.append(
            {
                "rule": item["rule"],
                "change": status,
                "before": old["status"] if old else None,
                "after": item["status"],
                "matches_before": len(old["result"].get("rows", [])) if old else None,
                "matches_after": len(item["result"].get("rows", [])),
            }
        )
    return {
        "baseline": before["run_id"],
        "changes": changes,
        "not_checked": sorted(set(previous) - {o["rule"] for o in after["checks"]}),
    }
