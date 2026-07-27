"""The candidate cut must leave room for the recency bump.

The fuzzy channels rank on ``similarity + recency_bump``, but the bump needs a
row's mtime, which the mapped store does not hold — it is only known after the
surviving slots are resolved back to rows. So the pre-filter has to cut below
the threshold by the largest bump that could still be applied.

Getting this wrong is silent. It does not raise, it does not empty the results,
it just quietly drops every file whose similarity sits in the bump's width below
the cutoff. Measured on the kernel index when it was wrong: 251 qualifying files
became 49, a strict subset of the correct answer, with the threshold and the
similarities themselves identical to seven decimal places.
"""

from __future__ import annotations

import numpy as np

from ken.ranker.channels import FUZZY_RECENCY_BUMP, _top_slots


def test_headroom_keeps_candidates_the_bump_could_rescue():
    thr = 0.40
    sims = np.array([0.45, 0.399, 0.35, 0.301, 0.299, 0.20], dtype=np.float32)
    slots = np.arange(sims.size, dtype=np.int64)

    kept, _ = _top_slots(sims, slots, thr, headroom=FUZZY_RECENCY_BUMP)

    # Everything down to thr - bump survives the cut: a freshly edited file at
    # 0.301 reaches 0.401 once the full 0.10 bump lands, so dropping it here
    # would lose a legitimate hit.
    assert set(kept.tolist()) == {0, 1, 2, 3}
    # 0.299 cannot reach the threshold even with the largest possible bump.
    assert 4 not in kept.tolist()
    assert 5 not in kept.tolist()


def test_without_headroom_the_cut_is_exact():
    thr = 0.40
    sims = np.array([0.45, 0.399, 0.35], dtype=np.float32)
    slots = np.arange(sims.size, dtype=np.int64)

    kept, _ = _top_slots(sims, slots, thr)

    # doc-intent applies no bump, so its channel wants the exact cut.
    assert kept.tolist() == [0]


def test_the_cap_still_applies_and_keeps_the_strongest(monkeypatch):
    import ken.ranker.channels as channels

    monkeypatch.setattr(channels, "FUZZY_RESOLVE_CAP", 3)
    sims = np.linspace(0.5, 0.9, 10).astype(np.float32)
    slots = np.arange(sims.size, dtype=np.int64)

    kept, kept_sims = channels._top_slots(sims, slots, 0.0)

    assert kept.size == 3
    assert sorted(kept.tolist()) == [7, 8, 9]
    assert float(kept_sims.min()) >= float(sims[6])
