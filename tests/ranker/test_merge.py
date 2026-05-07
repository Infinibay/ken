"""Merge: max-by-target + synergy bonus."""

from __future__ import annotations

import pytest

from ken.ranker import RankedItem
from ken.ranker.merge import SYNERGY_BONUS, merge_files, merge_symbols


def _file(target: str, score: float, reason: str = "") -> RankedItem:
    return RankedItem(target=target, target_type="file", score=score, reason=reason)


def _sym(target: str, score: float, reason: str = "") -> RankedItem:
    return RankedItem(target=target, target_type="symbol", score=score, reason=reason)


def test_merge_takes_max_score(conn=None):  # noqa: ARG001
    """Single-channel-per-target keeps that channel's score (no synergy)."""
    out = merge_files([_file("a", 5.0, "reactive")])
    assert len(out) == 1
    assert out[0].score == pytest.approx(5.0)


def test_merge_synergy_bonus():
    """Bug fix #8: a target hit by 2 channels gets max + SYNERGY_BONUS."""
    a_reactive = _file("a", 5.0, "reactive")
    a_fuzzy = _file("a", 3.0, "fuzzy")
    out = merge_files([a_reactive], [a_fuzzy])
    assert len(out) == 1
    assert out[0].score == pytest.approx(5.0 + SYNERGY_BONUS)


def test_merge_synergy_scales_with_channel_count():
    """3 channels → +2× SYNERGY_BONUS, 4 → +3×, etc."""
    out = merge_files(
        [_file("a", 5.0, "explicit")],
        [_file("a", 3.0, "reactive")],
        [_file("a", 2.0, "fuzzy")],
    )
    assert out[0].score == pytest.approx(5.0 + 2 * SYNERGY_BONUS)


def test_merge_corroborated_beats_solo_when_close(conn=None):  # noqa: ARG001
    """A 2-channel hit at base 5.0 should now beat a 1-channel hit at 5.2."""
    out = merge_files(
        [_file("a", 5.0, "reactive"), _file("b", 5.2, "fuzzy")],
        [_file("a", 4.5, "fuzzy")],
    )
    by_target = {it.target: it.score for it in out}
    assert by_target["a"] > by_target["b"]
    assert by_target["a"] == pytest.approx(5.0 + SYNERGY_BONUS)
    assert by_target["b"] == pytest.approx(5.2)


def test_merge_keeps_reasons_concatenated():
    """All channels' reasons survive in the merged item, even if they
    didn't move the score."""
    out = merge_files(
        [_file("a", 5.0, "reactive:read_edit")],
        [_file("a", 3.0, "fuzzy:0.62")],
    )
    assert "reactive:read_edit" in out[0].reason
    assert "fuzzy:0.62" in out[0].reason


def test_merge_symbols_passthrough():
    """Symbols channel is just dedup-by-target with max-score."""
    out = merge_symbols([
        _sym("Foo (a.py:1)", 4.0),
        _sym("Foo (a.py:1)", 5.0),
        _sym("Bar (b.py:1)", 3.0),
    ])
    by_target = {it.target: it.score for it in out}
    assert by_target["Foo (a.py:1)"] == pytest.approx(5.0)
    assert by_target["Bar (b.py:1)"] == pytest.approx(3.0)


def test_ranked_item_lt_tiebreak_is_stable():
    """Bug fix #16: ties are broken alphabetically (after reverse=True)."""
    items = [
        RankedItem(target="zebra.py", target_type="file", score=5.0),
        RankedItem(target="apple.py", target_type="file", score=5.0),
        RankedItem(target="mango.py", target_type="file", score=5.0),
    ]
    items.sort(reverse=True)
    # All same score; expect alphabetical ascending after reverse.
    assert [it.target for it in items] == ["apple.py", "mango.py", "zebra.py"]
