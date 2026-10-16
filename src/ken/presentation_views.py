"""Select useful public context while retaining uncertainty and provenance.

The domain owns results. These projections only omit expandable diagnostic
traces; JSON and explicit full/explain keep them unchanged.
"""
from __future__ import annotations

from typing import Any


def compact_tool_result(name: str, value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if name == "ken_who":
        result = {k: v for k, v in value.items() if k != "responsibility_map"}
        candidates = []
        for candidate in value.get("candidates", []):
            row = {k: v for k, v in candidate.items() if k != "structure"}
            caveats = verification_caveats(candidate.get("structure", {}))
            if caveats:
                row["verification"] = caveats
            candidates.append(row)
        result["candidates"] = candidates
        caveats = verification_caveats(value.get("responsibility_map", {}))
        if caveats:
            result["verification"] = caveats
        return result
    if name == "ken_reason":
        result = {k: v for k, v in value.items() if k not in {"metrics", "reuse", "proof_note"}}
        if "answers" in value:
            result["answers"] = [{k: v for k, v in answer.items() if k != "proof"} |
                {"premise_sources": proof_sources(answer.get("proof"))}
                for answer in value["answers"]]
        if "metrics" in value:
            result["search"] = {k: v for k, v in value["metrics"].items()
                                if k in {"complete", "resumable", "pending"}}
        return result
    return value


def verification_caveats(value: Any, scope: str = "") -> list[str]:
    """Keep failed/unknown coverage when the successful trace is omitted."""
    if isinstance(value, list):
        return [note for item in value for note in verification_caveats(item, scope)]
    if not isinstance(value, dict):
        return []
    notes = []
    fields = []
    for key, item in value.items():
        if ((key in {"complete", "coverage_complete"} and item is False)
                or (key in {"unknown_candidates", "results_truncated"} and item)
                or (key in {"reason", "error", "warnings", "uncertainty"} and item)):
            fields.append(f"{key}={str(item).lower() if isinstance(item, bool) else item}")
        elif isinstance(item, (dict, list)):
            notes.extend(verification_caveats(item, f"{scope}.{key}".strip(".")))
    if fields:
        notes.insert(0, (scope + ": " if scope else "") + "; ".join(fields))
    return list(dict.fromkeys(notes))


def proof_sources(value: Any) -> list[str]:
    if isinstance(value, list):
        return sorted({s for item in value for s in proof_sources(item)})
    if not isinstance(value, dict):
        return []
    sources = []
    for key, item in value.items():
        if key == "source" and isinstance(item, str):
            sources.append(item)
        elif isinstance(item, (dict, list)):
            sources.extend(proof_sources(item))
    return sorted(set(sources))
