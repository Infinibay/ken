"""Signed semantic similarities for conditioning a ranker, not verified intent."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike


def _real(values: ArrayLike) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind not in 'fiu' or not np.isfinite(array).all():
        raise ValueError('finite real semantic vectors required')
    return np.array(array, dtype=np.float64, copy=True)


def _unit_rows(values: np.ndarray) -> np.ndarray:
    # Scaling first also defines the transformation for extreme finite inputs.
    scale = np.max(np.abs(values), axis=-1, keepdims=True)
    if np.any(scale == 0):
        raise ValueError('nonzero semantic direction required')
    scaled = values/scale
    return scaled/np.linalg.norm(scaled, axis=-1, keepdims=True)


@dataclass(frozen=True)
class SemanticContrasts:
    """Own immutable unit directions; project each query through the same formula."""
    axes: np.ndarray

    def __post_init__(self) -> None:
        axes = _real(self.axes)
        if (axes.ndim != 2 or not all(axes.shape)
                or not np.allclose(np.linalg.norm(axes, axis=1), 1., rtol=0., atol=1e-12)):
            raise ValueError('registered nonempty unit semantic contrast axes required')
        axes.setflags(write=False)
        object.__setattr__(self, 'axes', axes)

    @classmethod
    def from_pairs(cls, positive: ArrayLike, negative: ArrayLike) -> SemanticContrasts:
        a, b = _real(positive), _real(negative)
        if a.ndim != 2 or a.shape != b.shape or not all(a.shape):
            raise ValueError('paired nonempty semantic vector matrices required')
        return cls(_unit_rows(_unit_rows(a)-_unit_rows(b)))

    def project(self, vector: ArrayLike) -> np.ndarray:
        query = _real(vector)
        if query.shape != (self.axes.shape[1],):
            raise ValueError('one query vector of the registered dimension required')
        return self.axes@_unit_rows(query)


# Fixed generic contrasts: no repository, file, symbol or benchmark query text.
QUERY_CONTRASTS = (
    ('create_update', 'Find code that creates or initializes a new object.',
     'Find code that updates or operates on an existing object.'),
    ('parse_format', 'Find code that parses or validates an input representation.',
     'Find code that formats or serializes an output representation.'),
    ('failure_success', 'Find code that handles a failure or raises an error.',
     'Find code that returns normally when the operation succeeds.'),
    ('conditional_unconditional', 'Find code that executes an operation conditionally.',
     'Find code that executes an operation unconditionally.'),
    ('delegation_algorithm', 'Find code that calls or delegates to another implementation.',
     'Find code that directly implements an algorithm.'),
    ('choose_execute', 'Find code that chooses between alternate operations.',
     'Find code that performs one simple operation.'),
    ('ordered_independent', 'Find code that preserves the order of several operations.',
     'Find code that performs a single independent operation.'),
    ('release_acquire', 'Find code that frees resources or undoes earlier changes.',
     'Find code that acquires resources or applies new changes.'),
    ('fallback_abort', 'Find code that retries or falls back after a failed operation.',
     'Find code that aborts immediately after a failed operation.'),
    ('mutate_compute', 'Find code that changes an object or container in place.',
     'Find code that computes and returns a new value.'),
    ('async_sync', 'Find code that runs asynchronously and waits for completion.',
     'Find code that runs synchronously without waiting.'),
    ('iterate_access', 'Find code that iterates or filters a collection.',
     'Find code that accesses a single element directly.'),
    ('configure_apply', 'Find code that builds configuration or stores options.',
     'Find code that consumes configuration or applies stored options.'),
    ('missing_valid', 'Find code that handles missing, empty, or invalid values.',
     'Find code that processes ordinary valid values.'),
    ('test_implement', 'Find code that tests or asserts the behavior of another function.',
     'Find code that implements the behavior used by callers.'),
    ('entry_helper', 'Find code that defines a public entry point or interface.',
     'Find code that implements an internal helper or primitive.'),
)
