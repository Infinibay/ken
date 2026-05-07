"""Per-channel breakdown of a rank() call.

The regular ``rank()`` collapses all channels into a single sorted list.
That's right for prompt injection but useless for debugging "why didn't
file X show up?" — the merge stage hides the original signal.

``explain()`` re-runs each channel in isolation, snapshots the merged
list before every boost, and returns a structured dict the
``ken_explain_rank`` MCP tool surfaces verbatim. Cost is roughly 2× a
normal rank — fine for a debug-only path.
"""

from __future__ import annotations

import sqlite3
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
) -> dict[str, Any]:
    from ken.ranker import boosts, channels, merge

    similar = channels.similar_past_sessions(conn, prompt_embedding)

    explicit_files, explicit_symbols = channels.explicit_mentions(conn, prompt)
    reactive = channels.reactive_scores(conn, agent_id, current_iteration)
    predictive = channels.predictive_scores(conn, similar)
    fuzzy_files, fuzzy_symbols = channels.fuzzy_scores(conn, prompt_embedding)
    lexical_files, lexical_symbols = channels.lexical_scores(
        conn, prompt, agent_id=agent_id
    )
    findings = channels.finding_scores(conn, prompt_embedding)

    symbols = merge.merge_symbols([*explicit_symbols, *fuzzy_symbols, *lexical_symbols])
    symbols.sort(reverse=True)

    files = merge.merge_files(explicit_files, reactive, predictive, fuzzy_files, lexical_files)
    files.sort(reverse=True)
    pre_boost = {it.target: it.score for it in files}

    boosts.apply_symbol_file_affinity(conn, files, symbols)
    post_symbol_file = {it.target: it.score for it in files}

    boosts.apply_freshness(conn, files)
    post_fresh = {it.target: it.score for it in files}

    boosts.apply_cooc(conn, files)
    post_cooc = {it.target: it.score for it in files}

    boosts.apply_test_affinity(conn, files)
    post_test_affinity = {it.target: it.score for it in files}

    boosts.apply_import_affinity(conn, files)
    post_import_affinity = {it.target: it.score for it in files}

    boosts.apply_dismissal_penalty(conn, files, similar)
    post_dismiss = {it.target: it.score for it in files}

    files.sort(reverse=True)

    return {
        "prompt": prompt,
        "channels": {
            "explicit_files": _to_dicts(explicit_files, top),
            "explicit_symbols": _to_dicts(explicit_symbols, top),
            "reactive": _to_dicts(reactive, top),
            "predictive": _to_dicts(predictive, top),
            "fuzzy_files": _to_dicts(fuzzy_files, top),
            "fuzzy_symbols": _to_dicts(fuzzy_symbols, top),
            "lexical_files": _to_dicts(lexical_files, top),
            "lexical_symbols": _to_dicts(lexical_symbols, top),
            "findings": _findings_dicts(findings, top),
        },
        "merge_before_boosts": _scores_dict(pre_boost, top),
        "boosts": {
            "symbol_file_affinity": _diff(pre_boost, post_symbol_file),
            "freshness": _diff(post_symbol_file, post_fresh),
            "cooc": _diff(post_fresh, post_cooc),
            "test_affinity": _diff(post_cooc, post_test_affinity),
            "import_affinity": _diff(post_test_affinity, post_import_affinity),
            "dismissal": _diff(post_import_affinity, post_dismiss),
        },
        "final_files": _to_dicts(files, top),
        "final_symbols": _to_dicts(symbols, top),
        "final_findings": _findings_dicts(sorted(findings, reverse=True), top),
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
