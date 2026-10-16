"""Combine an existing candidate order with a reranker's ordinal evidence."""
from collections.abc import Sequence
import math


def fused_reranker_order(scores: Sequence[float], *, neural_weight: float = .5,
                         rank_offset: float = 60.) -> list[int]:
    """Return candidate indices using weighted, one-based reciprocal ranks.

    Scores refer to candidates in their existing order. Both neural ties and
    fusion ties preserve that order. No candidates are added or removed.
    """
    if not math.isfinite(neural_weight) or not 0. <= neural_weight <= 1.:
        raise ValueError('neural weight must lie in [0, 1]')
    if not math.isfinite(rank_offset) or rank_offset < 0.:
        raise ValueError('rank offset must be finite and nonnegative')
    if not all(math.isfinite(score) for score in scores):
        raise ValueError('finite reranker scores required')
    native = list(range(len(scores)))
    neural = sorted(native, key=lambda i: (-scores[i], i))
    positions = {index: rank for rank, index in enumerate(neural, 1)}
    return sorted(native, key=lambda i: (
        -((1. - neural_weight) / (rank_offset + i + 1)
          + neural_weight / (rank_offset + positions[i])), i))
