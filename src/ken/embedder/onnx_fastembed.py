"""ONNX-Runtime embedder backed by the ``fastembed`` Python package.

Default model: ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim).
fastembed handles the model download (cached under
``~/.cache/fastembed``), tokenisation, batching, and CPU-side ONNX
inference. ~25 MB on disk, ~5 ms per inference once warm.

Override the model with ``KEN_EMBED_MODEL`` (must be 384-dim or the
schema's ``vector(384)`` columns won't accept the bytes).

Threading: we serialise calls into fastembed under a single lock. The
underlying ONNX session is technically thread-safe but the Python
wrapper isn't, and for our load (a few inferences per file save) the
lock is invisible.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from fastembed import TextEmbedding

logger = logging.getLogger("ken.embedder")

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIM = 384


class OnnxEmbedder:
    """Lazy wrapper around fastembed.TextEmbedding."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("KEN_EMBED_MODEL", DEFAULT_MODEL)
        self._lock = threading.Lock()
        self._model: TextEmbedding | None = None
        self._dim = DEFAULT_DIM  # confirmed against the model after first call

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure_model(self) -> "TextEmbedding":
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                # Imported lazily so the daemon's cold start (and the
                # CLI's `ken status` / `ken hook session-start` paths)
                # don't pay for ORT bootstrap when they don't need it.
                from fastembed import TextEmbedding

                logger.info("loading fastembed model=%s", self.model_name)
                self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        model = self._ensure_model()
        with self._lock:
            # fastembed.embed returns a generator → realise into a list
            # so we hold the lock for the whole batch (tokeniser /
            # session aren't safe to share across threads).
            out = [np.asarray(v, dtype=np.float32) for v in model.embed(texts)]
        return out

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]
