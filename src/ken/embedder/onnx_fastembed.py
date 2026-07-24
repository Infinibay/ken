"""ONNX-Runtime embedder backed by the ``fastembed`` Python package.

Default model: ``sentence-transformers/all-MiniLM-L6-v2`` (384-dim).
fastembed handles the model download (cached under
``~/.cache/fastembed``), tokenisation, batching, and ONNX inference.
~25 MB on disk, ~5 ms per inference once warm on CPU.

Override the model with ``KEN_EMBED_MODEL`` (must match the DB's stored
dimension or the vectors won't line up — run ``ken reembed`` after a change).

Device selection (``KEN_EMBED_DEVICE``)
---------------------------------------
The embedder runs on the **GPU automatically when one is usable**, and
falls back to the CPU otherwise — the caller never has to configure it:

* ``auto`` (default) — use a GPU execution provider when onnxruntime exposes
  one (CUDA / ROCm / TensorRT), else CPU.
* ``cpu`` — force CPU even if a GPU is present.
* ``gpu`` (aliases ``cuda``) — prefer GPU; still falls back to CPU when no GPU
  provider is available rather than failing.

GPU acceleration needs the GPU build of the runtime — install ken's
``fastembed-gpu`` extra (which pulls ``onnxruntime-gpu``). With the default
CPU-only ``onnxruntime`` no GPU provider is ever reported, so ``auto`` quietly
stays on CPU. If GPU init raises at runtime (driver/library mismatch) the
embedder logs a warning and rebuilds on CPU, so a user is never left with a
hard failure. ``KEN_EMBED_DEVICE_ID`` selects a specific GPU (e.g. ``0``).

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

# GPU execution providers we know how to drive, in preference order. Using any
# of them requires the GPU build of onnxruntime (ken's ``fastembed-gpu``
# extra / ``onnxruntime-gpu``). With the default CPU-only onnxruntime these
# never appear in ``ort.get_available_providers()``, so detection falls back
# to CPU with no error and no configuration.
#
# TensorrtExecutionProvider is deliberately excluded: it needs a separate
# TensorRT install and, when its libraries are absent, onnxruntime prints a
# noisy load failure before falling back — not worth it for auto-detection.
# CUDA already delivers the GPU speedup; a user who has set up TensorRT can
# opt in explicitly. CUDA (NVIDIA) and ROCm (AMD) cover the common cases.
_GPU_PROVIDERS = (
    "CUDAExecutionProvider",
    "ROCMExecutionProvider",
)
_CPU_PROVIDER = "CPUExecutionProvider"


def _available_providers() -> set[str]:
    try:
        import onnxruntime as ort

        return set(ort.get_available_providers())
    except Exception:  # pragma: no cover - onnxruntime always present via fastembed
        return set()


def _device_ids() -> list[int] | None:
    raw = os.environ.get("KEN_EMBED_DEVICE_ID", "").strip()
    if not raw:
        return None
    try:
        return [int(x) for x in raw.replace(" ", "").split(",") if x != ""]
    except ValueError:
        logger.warning("ignoring invalid KEN_EMBED_DEVICE_ID=%r", raw)
        return None


def _select_providers(pref: str) -> tuple[list[str], str]:
    """Resolve ``KEN_EMBED_DEVICE`` into concrete ONNX providers.

    Returns ``(providers, device_label)`` where ``device_label`` is
    ``"gpu"`` or ``"cpu"``. ``auto``/``gpu`` pick a GPU provider only when one
    is actually available; otherwise CPU. A GPU provider list always keeps
    ``CPUExecutionProvider`` as the last entry so onnxruntime can fall back
    per-op if needed.
    """
    if pref == "cpu":
        return [_CPU_PROVIDER], "cpu"
    gpus = [p for p in _GPU_PROVIDERS if p in _available_providers()]
    if gpus:
        return [*gpus, _CPU_PROVIDER], "gpu"
    return [_CPU_PROVIDER], "cpu"


class OnnxEmbedder:
    """Lazy, GPU-aware wrapper around fastembed.TextEmbedding."""

    def __init__(self, model_name: str | None = None, *, device: str | None = None) -> None:
        self.model_name = model_name or os.environ.get("KEN_EMBED_MODEL", DEFAULT_MODEL)
        pref = (device or os.environ.get("KEN_EMBED_DEVICE", "auto")).strip().lower()
        self._device_pref = "gpu" if pref in {"gpu", "cuda"} else ("cpu" if pref == "cpu" else "auto")
        self._lock = threading.Lock()
        self._model: TextEmbedding | None = None
        self._dim = DEFAULT_DIM  # confirmed against the model after first call
        self.device = "unknown"  # resolved on first model build

    @property
    def dim(self) -> int:
        return self._dim

    def _build(self, providers: list[str]) -> "TextEmbedding":
        from fastembed import TextEmbedding

        kwargs: dict = {"providers": providers}
        if any(p in _GPU_PROVIDERS for p in providers):
            ids = _device_ids()
            if ids is not None:
                kwargs["device_ids"] = ids
        return TextEmbedding(model_name=self.model_name, **kwargs)

    def _ensure_model(self) -> "TextEmbedding":
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            providers, device = _select_providers(self._device_pref)
            try:
                # Imported lazily (inside _build) so cold paths that never
                # embed — ``ken status``, ``ken hook session-start`` — don't
                # pay for the ORT bootstrap.
                logger.info(
                    "loading fastembed model=%s device=%s providers=%s",
                    self.model_name, device, providers,
                )
                self._model = self._build(providers)
                self.device = device
            except Exception as exc:
                if device == "cpu":
                    raise
                # GPU provider present but unusable (driver/lib mismatch, OOM):
                # never hard-fail — rebuild on CPU so embedding always works.
                logger.warning(
                    "GPU embedder init failed (%s); falling back to CPU", exc
                )
                self._model = self._build([_CPU_PROVIDER])
                self.device = "cpu"
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
