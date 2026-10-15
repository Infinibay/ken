"""Small immutable query-only residual geometry; NumPy inference, no training runtime."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class QueryAdapter:
    down: np.ndarray
    up: np.ndarray | None = None

    def __post_init__(self):
        down = np.array(self.down, dtype=np.float32, copy=True)
        up = np.array(self.up, dtype=np.float32, copy=True) if self.up is not None else None
        if down.ndim != 2 or not np.isfinite(down).all() or min(down.shape) == 0:
            raise ValueError('finite nonempty query residual matrix required')
        if up is None:
            if down.shape[0] != down.shape[1]:
                raise ValueError('linear residual matrix must be square')
        elif (up.shape != (down.shape[1], down.shape[0]) or not np.isfinite(up).all()):
            raise ValueError('finite up matrix must restore the query dimension')
        down.setflags(write=False)
        if up is not None:
            up.setflags(write=False)
        object.__setattr__(self, 'down', down)
        object.__setattr__(self, 'up', up)

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(b'unit-query-residual-f32-v1\0')
        digest.update(str(self.down.shape).encode())
        digest.update(self.down.astype('<f4').tobytes())
        digest.update(b'linear' if self.up is None else b'tanh-bottleneck')
        if self.up is not None:
            digest.update(self.up.astype('<f4').tobytes())
        return digest.hexdigest()

    def transform(self, queries: np.ndarray) -> np.ndarray:
        queries = np.asarray(queries, dtype=np.float32)
        if queries.ndim != 2 or queries.shape[1] != self.down.shape[1] or not np.isfinite(queries).all():
            raise ValueError('finite query matrix of the residual input dimension required')
        correction = queries@self.down.T
        if self.up is not None:
            correction = np.tanh(correction)@self.up.T
        values = queries+correction
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if not np.isfinite(values).all() or np.any(norms <= 1e-12):
            raise ValueError('query residual requires finite nonzero outputs')
        return values/norms
