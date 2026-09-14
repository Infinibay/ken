"""Compact presentation of structural results.

The engine returns everything it knows: nested evidence trees, per-rule
outcomes, per-directory rollups, the analysed file list, and a copy of each
rule's full query text inside every finding. That is what a caller needs to
*audit* a finding, and far more than a caller needs to *read* one -- a 60
finding pattern scan over one package serialized 1.5 MB.

The default surface answers three questions per finding: what was found, where,
and with what confidence. ``--full`` (CLI) or ``full=True`` (MCP) restores the
verbatim payload; the engine's own result is untouched, only its default
rendering changes.
"""
from __future__ import annotations

from typing import Any

_NOTE = "Structural evidence consistent with an idiom; not proof of intent."


def _variant(finding: dict[str, Any]) -> str:
    """The catalogue variant that matched, for modern (union) rule queries.

    A root query is a union of variants and the engine reports ``variant`` as
    ``default`` for the union; the matching variant survives only in the
    evidence entry that names it.
    """
    variant = finding.get("variant")
    if variant and variant != "default":
        return str(variant)
    for item in finding.get("evidence") or []:
        query = item.get("query") if isinstance(item, dict) else None
        if isinstance(query, str) and "#" in query:
            return query.split("#", 1)[1]
    return str(variant or "default")


def _confidence(finding: dict[str, Any]) -> float:
    score = finding.get("evidence_score")
    return round(float(score), 3) if isinstance(score, (int, float)) else 1.0


def _place(finding: dict[str, Any]) -> dict[str, Any]:
    place: dict[str, Any] = {"path": finding.get("path", ""), "line": finding.get("line", 0)}
    symbol = finding.get("symbol")
    if symbol:
        place["symbol"] = symbol
    return place


def _graph_finding(finding: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"pattern": finding.get("id") or finding.get("pattern") or "",
                             "variant": _variant(finding),
                             "confidence": _confidence(finding),
                             **_place(finding)}
    status = finding.get("status")
    if status and status != "structural_match":
        entry["status"] = status
    unknown = finding.get("unknown")
    if unknown:
        entry["unknown"] = sorted(unknown)
    return entry


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        key = str(finding.get("id") or finding.get("pattern") or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _analysis(analysis: Any) -> dict[str, Any] | None:
    if not isinstance(analysis, dict):
        return None
    return {"files": len(analysis.get("files") or []),
            "skipped": len(analysis.get("skipped") or []),
            "coverage_complete": bool(analysis.get("coverage_complete", False)),
            "elapsed_ms": analysis.get("elapsed_ms")}


def _verdict(result: dict[str, Any], rendered: dict[str, Any]) -> None:
    if "outcomes" in result:
        rendered["complete"] = result.get("complete", True)
        incomplete = result.get("incomplete") or {}
        if incomplete:
            rendered["incomplete"] = incomplete


def present(result: dict[str, Any], *, kind: str = "patterns", detail: str = "compact") -> dict[str, Any]:
    """Render a structural response at the requested level of detail."""
    if detail == "full":
        return result
    rendered: dict[str, Any] = {"ok": result.get("ok", True)}
    if kind == "bugs":
        findings = result.get("findings")
        if not isinstance(findings, list):
            return result
        rendered["findings"] = [{"rule": item.get("id", ""), "severity": item.get("severity", ""),
                                 "message": item.get("message", ""), **_place(item)}
                                for item in findings]
    elif kind == "structure":
        matches = result.get("matches")
        if not isinstance(matches, list):
            return result
        rendered["matches"] = [{"bindings": item.get("bindings", {}),
                                "confidence": _confidence(item), **_place(item)}
                               for item in matches]
        rendered["count"] = len(matches)
    else:
        findings = result.get("findings")
        if not isinstance(findings, list):
            return result
        rendered["findings"] = [_graph_finding(item) for item in findings]
        rendered["summary"] = _counts(findings)
    if isinstance(rendered.get("findings"), list):
        rendered["count"] = len(rendered["findings"])
    _verdict(result, rendered)
    analysis = _analysis(result.get("analysis"))
    if analysis is not None:
        rendered["analysis"] = analysis
    rendered["note"] = _NOTE
    return rendered
