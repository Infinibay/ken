"""Masked pooling and full token counts for a CPU embedding control."""
from __future__ import annotations

from typing import Any

import numpy as np


def masked_mean(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if hidden.ndim != 3 or mask.shape != hidden.shape[:2] or not np.isfinite(hidden).all():
        raise ValueError('finite hidden vectors and matching mask required')
    counts = mask.sum(axis=1, keepdims=True)
    if np.any(counts <= 0):
        raise ValueError('nonempty document mask required')
    pooled = np.sum(hidden * mask[:,:,None], axis=1) / counts
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise ValueError('nonempty pooled vector required')
    return np.asarray(pooled / norms, dtype=np.float32)


def full_token_count(tokenizer: Any, text: str, *, lock: Any) -> int:
    with lock:
        previous = tokenizer.truncation
        tokenizer.no_truncation()
        try:
            return len(tokenizer.encode(text, add_special_tokens=False).ids)
        finally:
            if previous is not None:
                tokenizer.enable_truncation(**previous)
