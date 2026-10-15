"""Compact contextual token matching, independently of the source encoder."""
from __future__ import annotations

from functools import lru_cache

import numpy as np

STATISTICS = ('mean', 'minimum', 'quartile', 'weighted', 'above50', 'above70')
PROJECTION = 'rademacher-seed61-768x128-row-l2-int8-round127-v1'


@lru_cache(maxsize=1)
def projection_matrix() -> np.ndarray:
    matrix = np.random.default_rng(61).choice((-1., 1.), size=(768, 128)).astype(np.float32)
    matrix /= np.sqrt(np.float32(128))
    matrix.flags.writeable = False
    return matrix


def project_tokens(raw: np.ndarray) -> np.ndarray:
    """A fixed, label-independent projection is shared by source and query."""
    if (raw.ndim != 2 or raw.shape[1] != 768 or raw.dtype.kind not in 'fiu'
            or not np.isfinite(raw).all()):
        raise ValueError('finite768-dimensional token rows required')
    # For this scaled sign matrix, ||project(row)|| <= 768*max(abs(row)).
    # Leave a factor of two before squaring in the float32 norm; reject before
    # a wider input can overflow on cast. Ordinary encoder rows are unchanged.
    safe_component = np.sqrt(float(np.finfo(np.float32).max))/(2*768)
    if np.any(raw > safe_component) or np.any(raw < -safe_component):
        raise ValueError('token components exceed the safe float32 projection range')
    values = np.asarray(raw, dtype=np.float32) @ projection_matrix()
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or np.any(norms <= 1e-9):
        raise ValueError('contextual token projection produced a zero row')
    return values/norms


def compact_tokens(values: np.ndarray) -> np.ndarray:
    """Store unit vectors with one signed byte per component; no model weights."""
    if (values.ndim != 2 or values.shape[1] == 0 or not np.isfinite(values).all()
            or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5)):
        raise ValueError('finite unit token rows required for compaction')
    packed = np.rint(values*127).astype(np.int8)
    if np.any(np.linalg.norm(packed.astype(np.float32), axis=1) == 0):
        raise ValueError('quantization produced a zero token row')
    return packed


def interaction_statistics(query: np.ndarray, packed: np.ndarray,
                           weights: np.ndarray) -> tuple[float, ...]:
    """Summarize each contextual query token's strongest source match."""
    if (query.ndim != 2 or packed.ndim != 2 or not len(query)
            or query.shape[1] != packed.shape[1] or packed.dtype != np.int8
            or not np.isfinite(query).all()
            or not np.allclose(np.linalg.norm(query, axis=1), 1, atol=1e-5)
            or weights.shape != (len(query),) or not np.isfinite(weights).all()
            or np.any(weights <= 0)):
        raise ValueError('aligned finite unit query rows, int8 source and positive weights required')
    if not len(packed):
        return (0.,)*len(STATISTICS)
    source = packed.astype(np.float32)
    norms = np.linalg.norm(source, axis=1, keepdims=True)
    if np.any(norms <= 1e-9):
        raise ValueError('compact source contains a zero token row')
    source /= norms
    peaks = (query @ source.T).max(axis=1).astype(np.float64)
    return (float(peaks.mean()), float(peaks.min()), float(np.quantile(peaks, .25)),
            float(np.average(peaks, weights=weights)), float((peaks >= .5).mean()),
            float((peaks >= .7).mean()))
