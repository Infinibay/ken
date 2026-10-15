"""Fit a compact linear preference from equal-query joint code evidence."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from numpy.typing import ArrayLike


def _real(values: ArrayLike) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind not in 'fiu' or not np.isfinite(array).all():
        raise ValueError('finite real preference values required')
    return np.array(array, dtype=np.float64, copy=True)


def _unit_vectors(values: ArrayLike, *, empty: bool = False) -> np.ndarray:
    vectors = _real(values)
    if (vectors.ndim != 2 or not vectors.shape[1] or (not empty and not len(vectors))
            or np.any(np.abs(vectors) > 1.+1e-6)
            or not np.allclose(np.linalg.norm(vectors, axis=1), 1., rtol=0., atol=1e-6)):
        raise ValueError('nonempty compatible unit joint vector rows required')
    return vectors


def training_indices(eligible: ArrayLike, retrieval_rrf: ArrayLike, *,
                     max_negatives: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """Use only original eligibility and untrained retrieval, never a fitted ranker."""
    labels, priority = _real(eligible), _real(retrieval_rrf)
    if (labels.ndim != 1 or priority.shape != labels.shape
            or not np.isin(labels, (0., 1.)).all()
            or not isinstance(max_negatives, int) or isinstance(max_negatives, bool)
            or max_negatives <= 0):
        raise ValueError('binary eligibility and aligned untrained retrieval priorities required')
    positives = np.flatnonzero(labels == 1)
    negatives = np.flatnonzero(labels == 0)
    chosen = sorted(negatives, key=lambda index: (-priority[index], index))[:max_negatives]
    return positives, np.asarray(chosen, dtype=np.int64)


def preference_moments(positive: ArrayLike, negative: ArrayLike
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Average every positive/negative difference equally within one query."""
    positives, negatives = _unit_vectors(positive), _unit_vectors(negative)
    if positives.shape[1] != negatives.shape[1]:
        raise ValueError('matching joint vector dimensions required')
    dimension = positives.shape[1]
    gram, linear = np.zeros((dimension, dimension)), np.zeros(dimension)
    denominator = len(positives)*len(negatives)
    for row in positives:
        differences = row-negatives
        gram += differences.T@differences/denominator
        linear += differences.sum(axis=0)/denominator
    return gram, linear


@dataclass(frozen=True)
class LinearPreference:
    weights: np.ndarray

    def __post_init__(self) -> None:
        weights = _real(self.weights)
        if weights.ndim != 1 or not len(weights):
            raise ValueError('nonempty preference weight vector required')
        weights.setflags(write=False)
        object.__setattr__(self, 'weights', weights)

    def score(self, vectors: ArrayLike) -> np.ndarray:
        rows = _unit_vectors(vectors, empty=True)
        if rows.shape[1] != len(self.weights):
            raise ValueError('joint vector dimension differs from preference head')
        try:
            with np.errstate(over='raise', invalid='raise'):
                scores = rows@self.weights
        except FloatingPointError as exc:
            raise ValueError('preference scores must remain finite') from exc
        if not np.isfinite(scores).all():
            raise ValueError('preference scores must remain finite')
        return scores


def ridge_preference(gram: ArrayLike, linear: ArrayLike, *,
                     regularization: float = 1.) -> LinearPreference:
    """Solve sum of query mean squared preference errors plus L2 penalty."""
    covariance, target = _real(gram), _real(linear)
    if (target.ndim != 1 or not len(target)
            or covariance.shape != (len(target), len(target))
            or not np.allclose(covariance, covariance.T, rtol=0., atol=1e-10)
            or isinstance(regularization, bool) or not math.isfinite(regularization)
            or regularization <= 0):
        raise ValueError('compatible symmetric moments and positive L2 penalty required')
    matrix = covariance+regularization*np.eye(len(target))
    try:
        np.linalg.cholesky(matrix)
        weights = np.linalg.solve(matrix, target)
    except np.linalg.LinAlgError as exc:
        raise ValueError('regularized preference system must be positive definite') from exc
    if not np.allclose(matrix@weights, target, rtol=1e-10, atol=1e-10):
        raise ValueError('preference solution failed its normal-equation residual')
    return LinearPreference(weights)
