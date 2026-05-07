"""Merge per-channel scores into a single per-target ranking.

Strategy: for each target across the file channels, take the
``max()`` of its scores. This matches infinidev's "channels are
independent evidence" framing — the strongest signal wins, the
others don't compound. Reason strings concatenate so the renderer can
show *why* a file rose.

Symbols are simpler — only the fuzzy channel hits them today, so the
merge is a passthrough. (Reactive doesn't track per-symbol granularity
yet; we'd need PostToolUse to attach symbol IDs to interactions.)
"""

from __future__ import annotations

from ken.ranker import RankedItem


def merge_files(*channel_lists: list[RankedItem]) -> list[RankedItem]:
    by_path: dict[str, RankedItem] = {}
    for items in channel_lists:
        for it in items:
            if it.target_type != "file":
                continue
            existing = by_path.get(it.target)
            if existing is None:
                by_path[it.target] = RankedItem(
                    target=it.target,
                    target_type="file",
                    score=it.score,
                    reason=it.reason,
                )
            else:
                if it.score > existing.score:
                    existing.score = it.score
                # Always concatenate reasons so the renderer can show
                # the full provenance, even if a lower-scoring channel
                # also contributed.
                existing.reason = _join_reasons(existing.reason, it.reason)
    return list(by_path.values())


def merge_symbols(symbol_items: list[RankedItem]) -> list[RankedItem]:
    by_target: dict[str, RankedItem] = {}
    for it in symbol_items:
        if it.target_type != "symbol":
            continue
        existing = by_target.get(it.target)
        if existing is None or it.score > existing.score:
            by_target[it.target] = it
    return list(by_target.values())


def _join_reasons(a: str, b: str) -> str:
    if not a:
        return b
    if not b or b in a:
        return a
    return f"{a} | {b}"
