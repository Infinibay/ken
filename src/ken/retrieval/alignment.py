"""Measure how much of a query each source view explains with static vectors."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TermCoverage:
    mean: float = 0.
    minimum: float = 0.
    quartile: float = 0.
    above50: float = 0.
    above70: float = 0.
    weighted: float = 0.


class TermAlignment:
    """A query term gets one best match; repeating a document term adds no vote."""

    def __init__(self, query_vectors: np.ndarray, weights: np.ndarray):
        self.query_vectors = np.asarray(query_vectors)
        self.weights = np.asarray(weights)
        if self.query_vectors.ndim != 2 or not np.isfinite(self.query_vectors).all():
            raise ValueError('finite query term matrix required')
        if (self.weights.shape != (len(self.query_vectors),) or not np.isfinite(self.weights).all()
                or np.any(self.weights < 0)):
            raise ValueError('weights must be finite, nonnegative and match the query terms')

    def similarities(self, vocabulary_vectors: np.ndarray) -> np.ndarray:
        vectors = np.asarray(vocabulary_vectors)
        if (vectors.ndim != 2 or vectors.shape[1] != self.query_vectors.shape[1]
                or not np.isfinite(vectors).all()):
            raise ValueError('compatible finite document term matrix required')
        return self.query_vectors @ vectors.T

    def coverage(self, document_vectors: np.ndarray) -> TermCoverage:
        return self.summarize(self.similarities(document_vectors))

    def summarize(self, similarities: np.ndarray) -> TermCoverage:
        if (similarities.ndim != 2 or similarities.shape[0] != len(self.weights)
                or not np.isfinite(similarities).all()):
            raise ValueError('one finite similarity row per query term required')
        if not similarities.size:
            return TermCoverage()
        peaks = similarities.max(axis=1)
        return self.summarize_maxima(peaks[None, :], present=np.array([True]))[0]

    def summarize_maxima(self, maxima: np.ndarray, *, present: np.ndarray
                         ) -> tuple[TermCoverage, ...]:
        """Summarize many source views after their best term matches are known.

        Rows are source views and columns are query terms. Empty views remain
        distinct from measured zeros; their unfilled maxima may be nonfinite.
        """
        if (maxima.ndim != 2 or maxima.shape[1] != len(self.weights)
                or present.shape != (len(maxima),) or present.dtype != np.bool_
                or not np.isfinite(maxima[present]).all()):
            raise ValueError('aligned finite active maxima and boolean source presence required')
        rows = [TermCoverage()] * len(maxima)
        if not len(self.weights) or not present.any():
            return tuple(rows)
        active = maxima[present]
        denominator = max(1e-9, self.weights.sum())
        # Keep the original one-row dot reduction: a matrix-vector BLAS call
        # may choose a different floating-point accumulation order.
        weighted = (peak @ self.weights / denominator for peak in active)
        summaries = zip(active.mean(axis=1), active.min(axis=1),
            np.quantile(active, .25, axis=1), np.mean(active >= .5, axis=1),
            np.mean(active >= .7, axis=1), weighted, strict=True)
        for index, values in zip(np.flatnonzero(present), summaries, strict=True):
            rows[index] = TermCoverage(*(float(value) for value in values))
        return tuple(rows)
