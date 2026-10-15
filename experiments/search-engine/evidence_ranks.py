"""Reciprocal rank information without inventing differences between tied scores."""
from __future__ import annotations
import numpy as np


def reciprocal_evidence_rank(scores: np.ndarray) -> np.ndarray:
    values=np.asarray(scores)
    if values.ndim!=1 or values.dtype.kind not in 'fiu' or not np.isfinite(values).all():
        raise ValueError('finite real score vector required')
    if not len(values):
        return np.empty(0,dtype=np.float64)
    unique,inverse,counts=np.unique(values,return_inverse=True,return_counts=True)
    if len(unique)==1:
        return np.zeros(len(values),dtype=np.float64)
    ranks=len(values)-np.cumsum(counts)+(counts+1)/2.
    return 1./ranks[inverse]
