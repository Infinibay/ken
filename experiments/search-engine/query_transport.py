"""Small CPU-only identity-prior query geometry; no encoder or corpus access."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class QueryTransport:
    matrix: np.ndarray
    shift: np.ndarray
    normal_equation_residual: float

    def __post_init__(self):
        matrix = np.array(self.matrix, dtype=np.float64, copy=True)
        shift = np.array(self.shift, dtype=np.float64, copy=True)
        if (matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]
                or shift.shape != (matrix.shape[0],)
                or not np.isfinite(matrix).all() or not np.isfinite(shift).all()):
            raise ValueError('finite square query geometry and matching shift required')
        matrix.setflags(write=False)
        shift.setflags(write=False)
        object.__setattr__(self, 'matrix', matrix)
        object.__setattr__(self, 'shift', shift)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(b'query-transport-f64-to-unit-f32-v1\0'
            + self.matrix.astype('<f8').tobytes()+self.shift.astype('<f8').tobytes()).hexdigest()

    def transform(self, queries: np.ndarray) -> np.ndarray:
        queries = np.asarray(queries, dtype=np.float64)
        if queries.ndim != 2 or queries.shape[1] != len(self.shift) or not np.isfinite(queries).all():
            raise ValueError('finite query rows matching the transport dimension required')
        values = queries@self.matrix.T+self.shift
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if not np.isfinite(values).all() or np.any(norms <= 1e-12):
            raise ValueError('query transport requires nonzero finite outputs')
        return (values/norms).astype(np.float32)


def fit_transport(queries: np.ndarray, targets: np.ndarray, weights: np.ndarray, *,
                  regularization: float | None) -> QueryTransport:
    queries, targets = np.asarray(queries, dtype=np.float64), np.asarray(targets, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if (queries.ndim != 2 or not len(queries) or targets.shape != queries.shape
            or weights.shape != (len(queries),) or not np.isfinite(queries).all()
            or not np.isfinite(targets).all()):
        raise ValueError('matching finite nonempty question/target rows required')
    if not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('finite positive per-view weights required')
    dimension = queries.shape[1]
    identity = np.eye(dimension)
    if regularization is None:
        return QueryTransport(identity, np.average(targets-queries, axis=0, weights=weights), 0.)
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError('finite positive ridge regularization required')
    root_weights = np.sqrt(weights)[None, :]
    z = queries.T*root_weights
    residual_targets = (targets-queries).T*root_weights
    sample_system = z.T@z+regularization*np.eye(len(queries))
    correction = residual_targets@np.linalg.solve(sample_system, z.T)
    rhs = residual_targets@z.T
    residual = float(np.max(np.abs(correction@(z@z.T+regularization*identity)-rhs))
                     / max(1., float(np.max(np.abs(rhs)))))
    if residual > 1e-10:
        raise ValueError('query transport normal-equation residual exceeds tolerance')
    return QueryTransport(identity+correction, np.zeros(dimension), residual)
