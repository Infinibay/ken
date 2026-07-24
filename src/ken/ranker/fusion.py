"""Calibrated log-odds fusion (Phase 1).

An alternative to :func:`ranker.merge.merge_files` that treats each
channel as independent *evidence* rather than a raw magnitude to compare
directly. The pipeline:

1. **Calibrate** each channel's raw score to a probability
   ``P(relevant | this channel only)`` via a per-channel logistic map.
2. **Combine within a family** (semantic / lexical / behavioral /
   explicit) with a noisy-OR, so redundant same-family channels (e.g.
   fuzzy-file + doc-intent, both embedding-derived) *saturate* instead of
   double-counting.
3. **Sum log-odds across families**, weighted — this is where genuine
   cross-family corroboration is rewarded (the principled replacement for
   the flat synergy bonus).
4. **Rescale** the fused log-odds back to the legacy score magnitude, so
   the downstream boosts (freshness ×, cooc/affinity +, dismissal −) and
   the confidence gate keep working on a familiar range.

Selected by ``KEN_RANKER_FUSION=logodds``; the default remains the legacy
max+synergy merge so existing behavior and tests are untouched.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict

from ken.ranker import RankedItem


def fusion_mode() -> str:
    return os.environ.get("KEN_RANKER_FUSION", "legacy").strip().lower()


# ── Per-channel calibration ──────────────────────────────────────────
#
# Each channel maps its raw score to a probability. For threshold-gated
# channels we use a linear-in-logit map: raw==lo → p≈0.55, raw==hi → p≈0.90.
# Fixed-score channels (explicit mentions) get a flat probability.

_LOGIT_LO = 0.20   # logit(0.55)
_LOGIT_HI = 2.20   # logit(0.90)

# reason-prefix → (family, lo, hi)
#
# Family grouping is the load-bearing design decision: channels that draw
# on the SAME underlying evidence must share a family so their noisy-OR
# *saturates* instead of spuriously corroborating across the log-odds sum.
# fuzzy-file, doc-intent, lexical and literal are all name/text-derived —
# they are one family ("nametext"), not independent votes. Only genuinely
# independent evidence types (what the user NAMED, what is behaviorally
# hot) get their own family and thus cross-family credit.
_CALIB: dict[str, tuple[str, float, float]] = {
    "reactive": ("behavioral", 0.3, 6.0),
    "predictive": ("behavioral", 0.3, 6.0),
    "cooc": ("behavioral", 0.3, 3.0),
    "fuzzy": ("nametext", 0.3, 4.5),
    "doc-intent-symbol": ("nametext", 0.2, 2.1),
    "doc-intent": ("nametext", 0.2, 3.2),
    "literal": ("nametext", 1.15, 2.5),
    "lexical-context": ("nametext", 0.6, 1.4),
    "lexical": ("nametext", 0.6, 1.4),
}

# Fixed-probability channels keyed by reason prefix.
_FIXED: dict[str, tuple[str, float]] = {
    "explicit-mention": ("explicit", 0.93),
    "explicit-symbol-mention": ("explicit", 0.80),
    "explicit-line-mention": ("explicit", 0.95),
}

def _envf(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


_FAMILY_WEIGHT: dict[str, float] = {
    "explicit": _envf("KEN_FUSE_W_EXPLICIT", 1.30),
    "behavioral": _envf("KEN_FUSE_W_BEHAVIORAL", 1.15),
    "nametext": _envf("KEN_FUSE_W_NAMETEXT", 1.00),
}

# Rescale fused log-odds → legacy magnitude, and the confidence gate for
# this fusion mode. Tuned against the offline harness (curated + mined).
LOGODDS_SCALE = _envf("KEN_FUSE_SCALE", 1.6)
LOGODDS_GATE = _envf("KEN_FUSE_GATE", 1.5)


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(p / (1.0 - p))


def _channel_prob(reason: str, raw: float) -> tuple[str, float] | None:
    """Map one channel item to ``(family, probability)``."""
    prefix = reason.split(":", 1)[0].split(" ", 1)[0]
    if prefix in _FIXED:
        family, p = _FIXED[prefix]
        return family, p
    calib = _CALIB.get(prefix)
    if calib is None:
        # Unknown reason (a boost that ran pre-fusion, etc.) — treat as a
        # weak generic name/text signal rather than dropping it.
        calib = ("nametext", 0.3, 4.5)
    family, lo, hi = calib
    if hi <= lo:
        frac = 1.0
    else:
        frac = (raw - lo) / (hi - lo)
    frac = min(1.0, max(0.0, frac))
    logit = _LOGIT_LO + frac * (_LOGIT_HI - _LOGIT_LO)
    return family, _sigmoid(logit)


def fuse_files(channel_lists: list[list[RankedItem]]) -> list[RankedItem]:
    """Log-odds fusion over per-channel file items.

    Mirrors ``merge_files``' signature contract (a list of per-channel
    item lists) but combines them probabilistically.
    """
    # target → family → list of probabilities
    by_target: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    reasons: dict[str, list[str]] = defaultdict(list)
    for items in channel_lists:
        for it in items:
            if it.target_type != "file":
                continue
            mapped = _channel_prob(it.reason, it.score)
            if mapped is None:
                continue
            family, p = mapped
            by_target[it.target][family].append(p)
            reasons[it.target].append(it.reason)

    out: list[RankedItem] = []
    for target, fam_probs in by_target.items():
        fused_logit = 0.0
        families_present = 0
        for family, probs in fam_probs.items():
            # Noisy-OR within the family: 1 - Π(1 - p).
            complement = 1.0
            for p in probs:
                complement *= 1.0 - p
            fam_p = 1.0 - complement
            weight = _FAMILY_WEIGHT.get(family, 1.0)
            fused_logit += weight * _logit(fam_p)
            families_present += 1
        score = max(0.0, LOGODDS_SCALE * fused_logit)
        reason = _dedup_reasons(reasons[target])
        if families_present > 1:
            reason += f" | fused×{families_present}fam"
        out.append(
            RankedItem(target=target, target_type="file", score=score, reason=reason)
        )
    return out


def _dedup_reasons(items: list[str]) -> str:
    seen: list[str] = []
    for r in items:
        if r not in seen:
            seen.append(r)
    return " | ".join(seen)
