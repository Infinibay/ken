"""Project selected memories into bounded, progressively expandable context."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from .records import enrich, for_topics


def clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summary(hit: dict) -> dict[str, Any]:
    data = hit.get("justification", {})
    return {
        "topic": hit["topic"],
        "conclusion": hit.get("content", ""),
        "conclusion_complete": True,
        "kind": data.get("kind", "note"),
        "validity": hit.get("validity", {"state": "untracked"}),
        "rationale": clip(data.get("rationale", ""), 240),
        "assumptions": data.get("assumptions", []),
        "sources": [
            {"path": e["path"], "note": e.get("note", "")}
            for e in data.get("evidence", [])
            if not e["path"].startswith(".ken/")
        ],
        "recheck": clip(data.get("recheck", ""), 160),
        "expand": {"topic": hit["topic"], "detail": "full"},
    }


def answer(hit: dict) -> dict[str, Any]:
    """First retrieval stage: a whole conclusion with its reuse boundaries."""
    result = summary(hit)
    result.pop("rationale")
    validity = hit.get("validity", {"state": "untracked"})
    state = validity["state"]
    result["validity"] = {"state": state}
    if state == "unchanged":
        result.pop("recheck")
        result["reuse"] = "consider_if_question_and_assumptions_match"
    else:
        result["reuse"] = "review_inputs_before_reusing"
        if validity.get("issues"):
            result["validity"]["issues"] = validity["issues"]
    if validity.get("checks"):
        result["validity"]["checks"] = [
            {k: check[k] for k in ("status", "validity", "rules")}
            for check in validity["checks"]
        ]
    return result


def compact(
    hits: list[dict], max_chars: int = 3000, *, detail: str = "summary"
) -> dict[str, Any]:
    """A hard JSON character budget, preserving whole records and omissions."""
    if not 300 <= max_chars <= 20000:
        raise ValueError("max_chars must be 300..20000")
    out: dict[str, Any] = {"memories": [], "omitted": len(hits), "detail": detail}
    if detail == "answer":
        out["validity_scope"] = (
            "Declared inputs only; the conclusion and assumptions are not independently proved."
        )
    for hit in hits:
        candidate = out | {
            "memories": out["memories"]
            + [answer(hit) if detail == "answer" else summary(hit)],
            "omitted": out["omitted"] - 1,
        }
        if len(json.dumps(candidate, ensure_ascii=False)) <= max_chars:
            out = candidate
        else:
            # A clipped conclusion can lose its negation, caveat or scope and
            # trigger needless re-reading. Offer a whole-record expansion
            # instead of presenting a prefix as the remembered conclusion.
            reference = {
                "topic": hit["topic"],
                "conclusion_omitted": True,
                "validity": {
                    "state": hit.get("validity", {}).get("state", "untracked")
                },
                "expand": {"topic": hit["topic"], "detail": "full"},
            }
            candidate = out | {
                "memories": out["memories"] + [reference],
                "omitted": out["omitted"] - 1,
            }
            if len(json.dumps(candidate, ensure_ascii=False)) <= max_chars:
                out = candidate
    return out


def recall_view(
    conn: sqlite3.Connection,
    result: Any,
    *,
    root: Path | None,
    detail: str,
    max_chars: int,
) -> Any:
    """Keep existing full shapes; topic recall now includes the finding itself."""
    if isinstance(result, list):
        hits = enrich(conn, result, root=root)
        return compact(hits, max_chars, detail=detail) if detail != "full" else hits
    if not isinstance(result, dict):
        return result
    result = dict(result)
    hits = []
    if result.get("topic"):
        focused = for_topics(conn, [result["topic"]], root=root)
        if focused:
            result["finding"] = focused[0]
            hits.extend(focused)
    for key in ("findings", "neighbors", "related"):
        if key in result:
            result[key] = enrich(conn, result[key], root=root)
            hits.extend(result[key])
    return compact(hits, max_chars, detail=detail) if detail != "full" else result


def brief_line(hit: dict, max_chars: int = 450) -> str:
    """Status precedes content, so clipping never hides a stale warning."""
    data = hit.get("justification", {})
    state = hit.get("validity", {}).get("state", "untracked")
    labels = {
        "unchanged": "dependencias sin cambios",
        "stale": "REVISAR: cambió una dependencia",
        "unknown": "REVISAR: vigencia desconocida",
        "untracked": "sin vigencia comprobada",
    }
    label = labels.get(state, "REVISAR")
    if data.get("kind") == "hypothesis":
        label += "; hipótesis"
    if data.get("assumptions"):
        label += "; supuestos pendientes"
    text = f"[{label}] {clip(hit['topic'], 120)} — {clip(hit.get('content', ''), 200)}"
    if state in {"stale", "unknown"}:
        issue = "; ".join(hit.get("validity", {}).get("issues", []))
        text += f". Revisar: {clip(data.get('recheck') or issue, 130)}"
    elif data.get("rationale"):
        text += f". Motivo: {clip(data['rationale'], 130)}"
    return clip(text, max_chars)


def render_brief(
    conn: sqlite3.Connection,
    topics: list[str],
    *,
    root: Path,
    max_chars: int = 1100,
    seen: dict[str, str] | None = None,
) -> str:
    hits = for_topics(conn, topics, root=root)
    header = "<ken-knowledge>\nVigencia de dependencias declaradas; conservar alcance y supuestos.\n"
    footer = '\nRecuperar conclusión: ken_recall(topic="…", detail="answer").\n</ken-knowledge>'
    lines: list[str] = []
    for hit in hits:
        if "justification" not in hit:
            continue
        signature = sha256(
            json.dumps(hit, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if seen is not None and seen.get(hit["topic"]) == signature:
            continue
        line = "- " + brief_line(hit)
        if len(header + "\n".join(lines + [line]) + footer) > max_chars:
            continue
        lines.append(line)
        if seen is not None:
            seen[hit["topic"]] = signature
    return header + "\n".join(lines) + footer if lines else ""
