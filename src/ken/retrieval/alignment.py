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
        return TermCoverage(float(peaks.mean()), float(peaks.min()),
            float(np.quantile(peaks, .25)), float(np.mean(peaks >= .5)),
            float(np.mean(peaks >= .7)), float(peaks @ self.weights / max(1e-9, self.weights.sum())))
