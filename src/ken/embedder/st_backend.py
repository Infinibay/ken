"""Opt-in sentence-transformers (torch) embedder backend.

Enables stronger models that fastembed does not ship — notably
``Qwen/Qwen3-Embedding-0.6B`` (the top scorer in ken's retrieval benchmark)
and ``BAAI/bge-m3``. Pulled in by the ``torch`` extra:

    pip install 'ken-rank[torch]'

Like the ONNX backend it is GPU-aware: it uses CUDA automatically when torch
sees a device, and falls back to CPU otherwise. ``KEN_EMBED_DEVICE``
(``auto`` | ``cpu`` | ``gpu``) and ``KEN_EMBED_DEVICE_ID`` override.

Some models need an asymmetric query/passage prompt (Qwen3 takes a task
instruction on the query; e5 wants ``query:`` / ``passage:``). The table lives
in :mod:`ken.embedder` so both backends apply the same policy; this one just
consults it.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger("ken.embedder")

# Code embedding texts are short ("function parse — Parse the config", a file's
# language + stem + top symbols). Some models (Qwen3-Embedding) default to a
# 32k context; sentence-transformers pads each batch to its longest sequence,
# so one long text would balloon a batch to tens of GB of attention memory.
# Cap the sequence length and keep batches small — both overridable via env.
_MAX_SEQ = int(os.environ.get("KEN_EMBED_MAX_SEQ", "512"))
_BATCH = int(os.environ.get("KEN_EMBED_BATCH", "16"))

# Reduce CUDA fragmentation on long reembeds (set before torch is imported).
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

def _resolve_device() -> str:
    pref = os.environ.get("KEN_EMBED_DEVICE", "auto").strip().lower()
    if pref == "cpu":
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            ids = os.environ.get("KEN_EMBED_DEVICE_ID", "").strip()
            if ids:
                first = ids.split(",")[0]
                return f"cuda:{int(first)}" if first.isdigit() else "cuda"
            return "cuda"
    except Exception:  # pragma: no cover
        pass
    return "cpu"


class SentenceTransformerEmbedder:
    """Lazy, GPU-aware wrapper around sentence_transformers.SentenceTransformer."""

    def __init__(self, model_name: str, *, device: str | None = None) -> None:
        self.model_name = model_name
        self._device_override = device
        self._lock = threading.Lock()
        self._model: SentenceTransformer | None = None
        self._dim = 0
        self.device = "unknown"
        from ken.embedder import prompts_for

        self._q_prompt, self._p_prompt = prompts_for(model_name)

    @property
    def dim(self) -> int:
        if self._dim == 0:
            self._ensure_model()
        return self._dim

    def _ensure_model(self) -> "SentenceTransformer":
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                device = self._device_override or _resolve_device()
                logger.info(
                    "loading sentence-transformers model=%s device=%s",
                    self.model_name, device,
                )
                try:
                    model = SentenceTransformer(
                        self.model_name, trust_remote_code=True, device=device
                    )
                    self.device = device
                except Exception as exc:
                    if device == "cpu":
                        raise
                    logger.warning(
                        "GPU load failed (%s); falling back to CPU", exc
                    )
                    model = SentenceTransformer(
                        self.model_name, trust_remote_code=True, device="cpu"
                    )
                    self.device = "cpu"
                # Bound memory: cap the context so a stray long text can't pad
                # a whole batch to the model's (possibly 32k) default.
                try:
                    cur = getattr(model, "max_seq_length", None)
                    if cur is None or cur > _MAX_SEQ:
                        model.max_seq_length = _MAX_SEQ
                except Exception:  # pragma: no cover - model without the attr
                    pass
                self._model = model
                # get_sentence_embedding_dimension was renamed; prefer the new name.
                get_dim = getattr(model, "get_embedding_dimension", None) or \
                    model.get_sentence_embedding_dimension
                self._dim = int(get_dim())
        return self._model

    def _encode(self, texts: list[str], prompt: str) -> list[np.ndarray]:
        model = self._ensure_model()
        with self._lock:
            arr = model.encode(
                [prompt + t for t in texts] if prompt else texts,
                batch_size=_BATCH,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            self._free_vram()
        return [np.asarray(v, dtype=np.float32) for v in arr]

    def _free_vram(self) -> None:
        # Release cached blocks between batches so a long reembed doesn't
        # accumulate fragmentation on the GPU.
        if not str(self.device).startswith("cuda"):
            return
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # pragma: no cover
            pass

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        return self._encode(texts, self._p_prompt)

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        return self._encode(texts, self._q_prompt)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([text], self._q_prompt)[0]
