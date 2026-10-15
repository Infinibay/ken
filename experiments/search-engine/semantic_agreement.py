"""Compare matching signed contrasts without inventing a new vector space."""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def _coordinates(values: ArrayLike) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind not in 'fiu' or not np.isfinite(array).all():
        raise ValueError('finite real signed cosine coordinates required')
    real = np.array(array, dtype=np.float64, copy=True)
    if np.any(np.abs(real) > 1.+1e-12):
        raise ValueError('finite real signed cosine coordinates required')
    return real


def agreement_features(query: ArrayLike, candidates: ArrayLike) -> np.ndarray:
    """Return owner coordinates, signed agreements, and absolute differences.

    Correlated axes retain their original magnitudes; zero is a valid coordinate.
    A signed product records agreement along one axis, not behavioral entailment.
    """
    q, owners = _coordinates(query), _coordinates(candidates)
    if (q.ndim != 1 or not len(q) or owners.ndim != 2
            or owners.shape[1] != len(q)):
        raise ValueError('one query and compatible candidate contrast rows required')
    return np.column_stack((owners, owners*q, np.abs(owners-q)))
