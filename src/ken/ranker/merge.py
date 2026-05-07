"""Merge per-channel scores into a single per-target ranking.

Strategy: for each target, take the strongest channel's score as the
base, then add a small synergy bonus for every additional channel that
also surfaced the target. Reflects "channels are independent evidence,
so corroboration matters" — a file flagged by both reactive and fuzzy
should beat a file flagged by reactive alone of equal magnitude, but
the synergy stays small (constant, not magnitude-scaled) so a noisy
weak signal can't tip the result.

Reasons concatenate so the renderer can show full provenance even when
a lower-scoring channel didn't move the number.
"""

from __future__ import annotations

from collections import defaultdict

from ken.ranker import RankedItem

# How much each *additional* contributing channel adds to the merged
# score. Constant — a 4-channel target gets max + 1.5 regardless of the
# other channels' magnitudes. Tuned conservatively so synergy can't
# rescue a weak file unless real channels agree on it.
SYNERGY_BONUS = 0.5


def merge_files(*channel_lists: list[RankedItem]) -> list[RankedItem]:
    by_path: dict[str, RankedItem] = {}
    contribs: dict[str, int] = defaultdict(int)
    for items in channel_lists:
        for it in items:
            if it.target_type != "file":
                continue
            contribs[it.target] += 1
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
                existing.reason = _join_reasons(existing.reason, it.reason)

    for target, item in by_path.items():
        n = contribs[target]
        if n > 1:
            bonus = SYNERGY_BONUS * (n - 1)
            item.score += bonus
            item.reason = _join_reasons(item.reason, f"synergy×{n}(+{bonus:.1f})")
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
