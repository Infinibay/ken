"""Per-channel breakdown of a rank() call.

The regular ``rank()`` collapses all channels into a single sorted list.
That's right for prompt injection but useless for debugging "why didn't
file X show up?" — the merge stage hides the original signal.

``explain()`` runs the production pipeline once with snapshot collection
turned on. Its final results include the same fusion, boosts and confidence
gate as rank(); intermediate candidates remain available when the gate closes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from ken.ranker import FindingItem, RankedItem


def explain(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    current_iteration: int,
    prompt: str,
    prompt_embedding: np.ndarray,
    top: int = 10,
    project_root: Path | None = None,
    include_reactive: bool = True,
) -> dict[str, Any]:
    from ken.ranker import _RankTrace, rank

    trace = _RankTrace()
    result = rank(
        conn, agent_id=agent_id, current_iteration=current_iteration,
        prompt=prompt, prompt_embedding=prompt_embedding,
        top_files=top, top_symbols=top, top_findings=top,
        project_root=project_root, include_reactive=include_reactive, _trace=trace,
    )
    changes = {}
    before = trace.stages["merge"]
    for name, stage in trace.stages.items():
        if name in {"merge", "before_gate"}:
            continue
        changes[name] = _diff(
            {it.target: it.score for it in before.files},
            {it.target: it.score for it in stage.files},
        )
        if name == "language_intent":
            changes["language_symbol_intent"] = _diff(
                {it.target: it.score for it in before.symbols},
                {it.target: it.score for it in stage.symbols},
            )
        before = stage
    return {
        "prompt": prompt,
        "channels": {
            **{name: _to_dicts(items, top) for name, items in trace.channels.items()},
            "findings": _findings_dicts(trace.findings, top),
        },
        "merge_before_boosts": _scores_dict(
            {it.target: it.score for it in trace.stages["merge"].files}, top
        ),
        "boosts": changes,
        "confidence_gate": {"threshold": trace.gate, "suppressed": trace.suppressed},
        "candidates_before_gate": _to_dicts(trace.stages["before_gate"].files, top),
        "final_files": _to_dicts(result.files, top),
        "final_symbols": _to_dicts(result.symbols, top),
        "final_findings": _findings_dicts(result.findings, top),
    }


def _to_dicts(items: list[RankedItem], top: int) -> list[dict[str, Any]]:
    sortable = sorted(items, reverse=True)
    return [
        {"target": it.target, "score": round(it.score, 3), "reason": it.reason}
        for it in sortable[:top]
    ]


def _scores_dict(scores: dict[str, float], top: int) -> list[dict[str, Any]]:
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [{"target": k, "score": round(v, 3)} for k, v in ordered]


def _findings_dicts(items: list[FindingItem], top: int) -> list[dict[str, Any]]:
    sortable = sorted(items, reverse=True)
    return [
        {
            "topic": it.topic,
            "score": round(it.score, 3),
            "reason": it.reason,
            "tags": it.tags,
        }
        for it in sortable[:top]
    ]


def _diff(before: dict[str, float], after: dict[str, float]) -> list[dict[str, Any]]:
    """Items whose score changed (created, removed, or shifted)."""
    out: list[dict[str, Any]] = []
    for target in set(before) | set(after):
        b = before.get(target)
        a = after.get(target)
        if b == a:
            continue
        out.append(
            {
                "target": target,
                "before": None if b is None else round(b, 3),
                "after": None if a is None else round(a, 3),
                "delta": None if (a is None or b is None) else round(a - b, 3),
            }
        )
    out.sort(key=lambda r: abs(r.get("delta") or 0), reverse=True)
    return out
