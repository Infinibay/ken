"""Pattern classifier table tests.

These pin the priority order in `_classify_pattern`. Catches accidental
re-orderings (e.g. "did read_edit accidentally win over cited?") that
would shift productivity multipliers across the board.
"""

from __future__ import annotations

import pytest

from ken.ranker.channels import _classify_pattern


@pytest.mark.parametrize(
    ("events", "edited_elsewhere", "expected"),
    [
        # Cited beats everything when present (model cited the file).
        (["read", "edit", "cited"], False, "cited"),
        (["dismissed", "cited"], False, "cited"),
        (["cited"], False, "cited"),
        # Dismissed beats everything except cited.
        (["read", "edit", "dismissed"], False, "dismissed"),
        (["dismissed"], False, "dismissed"),
        # read + edit (or write) → read_edit.
        (["read", "edit"], False, "read_edit"),
        (["read", "write"], False, "read_edit"),
        (["retrieved", "edit"], False, "read_edit"),
        # edit alone → edit_only.
        (["edit"], False, "edit_only"),
        (["write"], False, "edit_only"),
        # ≥3 reads with no edit → read_repeated. The "you're stuck" pattern.
        (["read", "read", "read"], False, "read_repeated"),
        (["read", "retrieved", "read", "read"], False, "read_repeated"),
        # Read + edit-elsewhere → read_skipped.
        (["read"], True, "read_skipped"),
        (["read", "read"], True, "read_skipped"),
        # Single read, no edits anywhere → neutral.
        (["read"], False, "neutral"),
        # Empty events → neutral (degenerate but possible).
        ([], False, "neutral"),
    ],
)
def test_pattern_classification(events, edited_elsewhere, expected):
    assert _classify_pattern(events, edited_elsewhere=edited_elsewhere) == expected
