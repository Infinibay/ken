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
        return responsibility_text(value)
    if name == "ken_check":
        return {k: v for k, v in value.items() if k not in {"created_at", "claim"}
                and not (k == "scope" and v == "project")
                and not (k == "selection" and v == ".")}
    if name == "ken_calculate" and value.get("status") == "calculated" and isinstance(value.get("exact"), (str, int, float)):
        return f"{value['expression']} = {value['exact']}"
    if name == "ken_recall" and "memories" in value:
        result = {k: v for k, v in value.items() if k not in {"detail", "validity_scope"} and not (k == "omitted" and v == 0)}
        result["memories"] = [{k: v for k, v in m.items()
            if k not in {"expand", "reuse"} and not (k == "conclusion_complete" and v is True)
            and not (k == "kind" and v == "note")} for m in value["memories"]]
        return result
    if name == "ken_related" and "imports" in value and "neighbors" in value:
        result = {k: v for k, v in value.items() if k not in {"imports", "imported_by", "tests", "neighbors"}}
        seen = set()
        for group in ("imports", "imported_by", "tests", "neighbors"):
            rows = []
            for item in value.get(group, []):
                path = item if isinstance(item, str) else item.get("path") or item.get("file") or item.get("module")
                if not path or group == "neighbors" and path in seen:
                    continue
                rows.append(path)
                seen.add(path)
            if rows:
                result[group] = rows
        return result
    if name == "ken_reason":
        result = {k: v for k, v in value.items() if k not in {"metrics", "reuse", "proof_note", "question", "query", "revision"}
                  and not (k == "answers_truncated" and v is False)
                  and not (k == "context" and v == "main") and not (k == "world" and v == "base")}
        if "answers" in value:
            result["answers"] = [{k: v for k, v in answer.items() if k != "proof"} |
                {"premise_sources": proof_sources(answer.get("proof"))}
                for answer in value["answers"]]
        if "metrics" in value:
            result["search"] = {k: v for k, v in value["metrics"].items()
                                if k == "complete" or k in {"resumable", "pending"} and v}
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


def responsibility_text(value: dict[str, Any]) -> str:
    """A location and real code per hypothesis; detailed machinery stays opt-in."""
    from ken.retrieval.public import render
    status = value.get("status", "unknown")
    blocks = ["Ambiguous candidates:" if status == "ambiguous" else
              "Candidates:" if status == "candidates" else "No responsible owner established."]
    if value.get("reason"):
        blocks.append(value["reason"])
    verification = []
    shown: dict[tuple[str, int], str] = {}
    for group in ("candidates", "counterevidence"):
        if group == "counterevidence" and value.get(group):
            blocks.append("Counterevidence:")
        for candidate in value.get(group, []):
            evidence = candidate.get("snippets", [])
            symbol = candidate.get("symbol") or candidate.get("qualname")
            fresh, repeated = _fresh_source(candidate["path"], evidence, shown)
            if fresh:
                row = {"path": candidate["path"], "entity": {"qualname": symbol},
                       "evidence": fresh, "truncated": candidate.get("truncated", False),
                       "piece_kind": candidate.get("kind")}
                block = render({"results": [row]})
            else:
                block = candidate["path"] + (f":{candidate['line']}" if candidate.get("line") else "")
                if symbol:
                    block += " :: " + symbol
                if candidate.get("kind") in {"class", "module", "file"}:
                    block += " (" + candidate["kind"] + ")"
                if candidate.get("preview_unavailable"):
                    block += "\nCode unavailable: " + candidate["preview_unavailable"]
            if repeated:
                block += "\nAlso shown above: " + ", ".join(repeated) + "."
            quote = candidate.get("evidence")
            if isinstance(quote, str) and not any(quote in e["content"] for e in evidence):
                block += "\nDocumentation: " + quote
            if candidate.get("assumed_formulation"):
                block += "\nAssumed wording: " + candidate["assumed_formulation"]
            for field in ("caveats", "counterevidence", "assumptions"):
                for note in candidate.get(field, []):
                    block += "\n" + note
            verification.extend(verification_caveats(candidate.get("structure", {})))
            blocks.append(block)
    verification.extend(verification_caveats(value.get("responsibility_map", {})))
    notes = []
    for note in verification:
        # Repeated internal scopes do not change the useful coverage statement.
        note = note.split(": ", 1)[-1]
        if "usage_inventory_open" in note:
            note = "Call verification incomplete."
        if note not in notes:
            notes.append(note)
    if notes:
        blocks.append("Verification: " + " ".join(notes))
    if value.get("uninspected_candidates"):
        blocks.append(f"{value['uninspected_candidates']} candidates could not be read.")
    return "\n\n".join(blocks)



def _fresh_source(path: str, fragments: list[dict[str, Any]], shown: dict[tuple[str, int], str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Deduplicate identical physical source, retaining explicit cross-references."""
    fresh: list[dict[str, Any]] = []
    repeated: list[list[int]] = []
    for fragment in fragments:
        for offset, line in enumerate(fragment["content"].split("\n")):
            number = fragment["start_line"] + offset
            if shown.get((path, number)) == line:
                if repeated and repeated[-1][1] == number-1:
                    repeated[-1][1] = number
                else:
                    repeated.append([number, number])
            else:
                shown[path, number] = line
                if fresh and fresh[-1]["end_line"] == number-1:
                    fresh[-1]["end_line"] = number
                    fresh[-1]["content"] += "\n" + line
                else:
                    fresh.append({"start_line": number, "end_line": number, "content": line})
    return fresh, [f"{path}:{a}-{b}" for a, b in repeated]
