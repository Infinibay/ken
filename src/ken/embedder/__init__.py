"""Text embedder used by the indexer (file/symbol embeddings) and by
the daemon (cr_contexts embeddings, query embeddings for the ranker).

One concrete backend for now — `onnx_fastembed.OnnxEmbedder` — which
wraps the Python ``fastembed`` package. The MNN / ChromaDB selection
infinidev does at runtime is overkill while we have a single backend;
when we add MNN we can add a switch here.

Public entrypoint:

    from ken.embedder import get_embedder
    e = get_embedder()       # process-wide singleton
    vecs = e.embed_passages(["hello", "world"])  # → list[np.ndarray] (384,)

Embedders are **lazy**: the model file is only downloaded + the ONNX
session only built on the first call to an `embed_*` method. That
means a daemon that never gets a prompt (e.g. a session that only
opens and closes) never pays the model-load cost.
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

EMBEDDING_DIM = 384


class Embedder(Protocol):
    """Minimal embedder contract."""

    @property
    def dim(self) -> int: ...
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...


_lock = threading.Lock()
_singleton: Embedder | None = None


def get_embedder() -> Embedder:
    """Return the process-wide embedder singleton, building it on first use."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is None:
            from ken.embedder.onnx_fastembed import OnnxEmbedder

            _singleton = OnnxEmbedder()
    return _singleton


def embed_symbol_text(kind: str, name: str, docstring: str | None) -> str:
    """Canonical text we hand the embedder for a symbol.

    Mirrors infinidev's format so retrieval calibration carries over.
    """
    tail = (docstring or "").strip()
    return f"{kind} {name} — {tail}" if tail else f"{kind} {name}"


def embed_file_text(language: str | None, stem: str, top_symbols: list[str]) -> str:
    """Canonical file-level embedding text. Captures the file *role* —
    language + base name + a few top-of-file symbol names — without
    embedding the whole content (which would dominate any retrieval).
    """
    lang = language or "text"
    if top_symbols:
        return f"{lang} {stem} — {' '.join(top_symbols)}"
    return f"{lang} {stem}"


def vec_to_blob(vec: np.ndarray) -> bytes:
    """Serialise a 384-dim float32 array for SQLite storage."""
    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes | memoryview) -> np.ndarray:
    """Deserialise; returns a read-only view backed by the supplied bytes."""
    return np.frombuffer(bytes(blob), dtype=np.float32)
