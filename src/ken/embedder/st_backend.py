"""Opt-in sentence-transformers (torch) embedder backend.

Enables stronger models that fastembed does not ship — notably
``Qwen/Qwen3-Embedding-0.6B`` (the top scorer in ken's retrieval benchmark)
and ``BAAI/bge-m3``. Pulled in by the ``torch`` extra:

    pip install 'ken-rank[torch]'

Like the ONNX backend it is GPU-aware, and here that includes **Apple
Silicon**: torch's MPS backend is used when the machine has one, CUDA when it
has that, and the CPU otherwise — no configuration.  ``KEN_EMBED_DEVICE``
(``auto`` | ``cpu`` | ``gpu`` | ``cuda`` | ``mps``) and ``KEN_EMBED_DEVICE_ID``
override.

MPS is held to a lower level of trust than CUDA. It is a younger backend, some
operators are still missing from it, and — the part that matters for an index —
it can return NaN instead of raising. So an accelerator that fails *either* way
demotes itself to the CPU for the rest of the process rather than writing
poisoned vectors into the DB (see ``_encode_guarded``).

Some models need an asymmetric query/passage prompt (Qwen3 takes a task
instruction on the query; e5 wants ``query:`` / ``passage:``). The table lives
in :mod:`ken.embedder` so both backends apply the same policy; this one just
consults it.
"""

from __future__ import annotations

import logging
import os
import sys
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

# Apple Silicon only: when a model reaches for an operator torch has not
# implemented for MPS, run *that operator* on the CPU instead of raising. It is
# the cheaper repair — the rest of the graph stays on the GPU, where the
# whole-model fallback below would have moved everything. Like the CUDA knob it
# has to be set before torch is imported, hence module scope.
if sys.platform == "darwin":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


# torch versions below this silently corrupted MPS embeddings: the 2.8 fast
# path mishandled non-contiguous q/k/v in SDPA (pytorch#163597), which produced
# *finite, unit-norm, wrong* vectors — the one failure class none of the runtime
# guards below can detect. It was reported against sentence-transformers with an
# ordinary embedding model and fixed in 2.9.0, and the sentence-transformers
# maintainer's advice was blunt: do not use torch 2.8 on MPS. So ken refuses the
# GPU there rather than trusting an index it cannot check.
_MPS_MIN_TORCH = (2, 9)


def _torch_version(torch) -> tuple[int, int] | None:
    """``(major, minor)`` from ``torch.__version__``, or None if unparseable.

    Unparseable means *don't block* — a nightly or a vendor build is not
    evidence of the bug, and refusing the GPU over a version string we failed to
    read would be its own kind of wrong.
    """
    parts = str(getattr(torch, "__version__", "")).split("+")[0].split(".")
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):
        return None


def _mps_available(torch) -> bool:
    """Whether this machine has an Apple Silicon GPU ken is willing to use.

    ``is_available()`` rather than ``is_built()``: the latter is a compile-time
    flag, true on every macOS arm64 wheel regardless of the hardware. The call
    is wrapped because a stray raise here would take down embedding entirely,
    and the CPU is always a correct answer.
    """
    try:
        if not torch.backends.mps.is_available():
            return False
    except Exception:
        return False
    version = _torch_version(torch)
    if version is not None and version < _MPS_MIN_TORCH:
        logger.warning(
            "torch %s is below %d.%d, where MPS could return silently wrong "
            "embeddings (pytorch#163597); using the CPU instead",
            getattr(torch, "__version__", "?"), *_MPS_MIN_TORCH,
        )
        return False
    return True


def _cuda_device() -> str:
    """``cuda``, or ``cuda:N`` when KEN_EMBED_DEVICE_ID names an index."""
    ids = os.environ.get("KEN_EMBED_DEVICE_ID", "").strip()
    if ids:
        first = ids.split(",")[0]
        if first.isdigit():
            return f"cuda:{int(first)}"
    return "cuda"


def _resolve_device() -> str:
    """The torch device string to load on, from ``KEN_EMBED_DEVICE``.

    ``auto`` (the default) and ``gpu`` prefer CUDA, then Apple Silicon's MPS,
    then the CPU. Naming one accelerator (``cuda`` / ``mps``) restricts the
    choice to that one — asking for CUDA on a Mac lands on the CPU rather than
    silently substituting the other GPU, because the reason someone pins a
    device is usually that they are comparing it against another.
    """
    pref = os.environ.get("KEN_EMBED_DEVICE", "auto").strip().lower()
    if pref == "cpu":
        return "cpu"
    try:
        import torch
    except Exception:  # pragma: no cover - torch ships with this backend
        return "cpu"
    if pref in {"auto", "gpu", "cuda"} and torch.cuda.is_available():
        return _cuda_device()
    if pref in {"auto", "gpu", "mps"} and _mps_available(torch):
        return "mps"
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

    def _cap_mps_memory(self) -> None:
        """Make an oversized batch raise instead of wedging the machine.

        torch's MPS allocator defaults to a high-watermark of ~1.7× Metal's
        recommended working set, which is itself a fraction of physical RAM — so
        on a typical Mac the ceiling sits *above* the RAM that exists. The
        allocator therefore never reports out-of-memory: macOS just swaps until
        the laptop stops responding, and ``_encode_guarded``'s demote-on-raise
        never fires because nothing raises. Capping the fraction converts that
        into the ``RuntimeError`` that path already knows how to handle.

        Process-global, which is fine for ken's own daemon but would be
        inherited by a host process that also drives MPS — hence the env knob.
        """
        try:
            import torch

            frac = float(os.environ.get("KEN_MPS_MEMORY_FRACTION", "0.7"))
            torch.mps.set_per_process_memory_fraction(frac)
        except Exception as exc:  # pragma: no cover - non-MPS build / old torch
            logger.debug("could not cap MPS memory: %s", exc)

    def _build(self, device: str) -> "SentenceTransformer":
        """Load the model onto *device*. Callers hold ``self._lock``."""
        from sentence_transformers import SentenceTransformer

        logger.info(
            "loading sentence-transformers model=%s device=%s",
            self.model_name, device,
        )
        if device.startswith("mps"):
            self._cap_mps_memory()
        # Deliberately no ``tokenizer_kwargs``. The Qwen3-Embedding model card
        # recommends ``padding_side="left"``, and on MPS that is the documented
        # route to all-NaN embeddings (sentence-transformers#3498): left padding
        # on a causal model creates a fully-masked attention row, and Metal's
        # softmax answers NaN where the CPU answers zeros. The tokenizer default
        # is right padding, which never builds such a row, and this model's
        # last-token pooling handles either side. Do not "fix" this by copying
        # the model card. (Nor ``attn_implementation="flash_attention_2"``,
        # also from the card: FA2 has no Apple Silicon support at all.)
        model = SentenceTransformer(
            self.model_name, trust_remote_code=True, device=device
        )
        # Bound memory: cap the context so a stray long text can't pad a whole
        # batch to the model's (possibly 32k) default.
        try:
            cur = getattr(model, "max_seq_length", None)
            if cur is None or cur > _MAX_SEQ:
                model.max_seq_length = _MAX_SEQ
        except Exception:  # pragma: no cover - model without the attr
            pass
        return model

    def _ensure_model(self) -> "SentenceTransformer":
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                device = self._device_override or _resolve_device()
                try:
                    model = self._build(device)
                    self.device = device
                except Exception as exc:
                    if device == "cpu":
                        raise
                    logger.warning(
                        "loading on %s failed (%s); falling back to CPU",
                        device, exc,
                    )
                    model = self._build("cpu")
                    self.device = "cpu"
                self._model = model
                # get_sentence_embedding_dimension was renamed; prefer the new name.
                get_dim = getattr(model, "get_embedding_dimension", None) or \
                    model.get_sentence_embedding_dimension
                self._dim = int(get_dim())
        return self._model

    def _run(self, model: "SentenceTransformer", payload: list[str]) -> np.ndarray:
        return model.encode(
            payload,
            batch_size=_BATCH,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def _looks_encoded(self, arr: np.ndarray) -> bool:
        """Whether a batch looks like real embeddings — both ways a GPU lies.

        NaN and Inf are the loud lie, and the obvious check. The quiet one is a
        row the GPU never actually filled in: ``_run`` asks for normalised
        output, and torch's ``F.normalize`` divides by a *clamped* norm, so an
        all-zero row survives normalisation as an all-zero row. It is finite, it
        passes any is-finite test, it reaches ``ken.db``, and it then scores 0.0
        against every query for the life of the index. Since normalisation was
        requested, every row owes us a unit vector — checking that catches both
        classes at once, for one norm over a small batch.

        What it cannot catch is finite, unit-norm, *wrong-direction* output.
        Nothing short of re-encoding on the CPU would, and that means a second
        copy of the weights resident — a worse risk on a shared-memory Mac than
        the one it removes. That gap is why ``_MPS_MIN_TORCH`` exists: the known
        silent-corruption bug is excluded by version, not by inspection.
        """
        if not np.isfinite(arr).all():
            return False
        norms = np.linalg.norm(np.atleast_2d(arr), axis=1)
        return bool(np.abs(norms - 1.0).max() < 1e-3)

    def _encode_guarded(self, payload: list[str]) -> np.ndarray:
        """Encode *payload*, demoting a broken accelerator instead of trusting it.

        A GPU can fail two ways here and the second is the dangerous one. It can
        **raise** — an operator the backend never implemented, an out-of-memory,
        a driver mismatch — which is loud and easy. Or it can hand back
        something that is not an embedding at all, which is silent: the vector
        is written to ``ken.db`` and shows up months later as retrieval that
        quietly got worse. ``_looks_encoded`` is a few microseconds on a batch
        this size, so both paths are treated the same — rebuild on the CPU once
        for the life of the process and redo the batch. Loading is what got
        cheaper by then (the weights are already in the HF cache), and
        correctness is the thing the index cannot recover on its own.

        Demoting mid-run leaves an index written partly on the GPU and partly on
        the CPU. That is fine, and worth being explicit about: it is the same
        weights and the same arithmetic either way, so the two differ at
        float-rounding scale — unlike two *models*, which is what
        ``EmbeddingSpaceMismatch`` and ``ken reembed`` exist for.

        Callers hold ``self._lock``; the rebuild deliberately goes through
        ``_build`` rather than ``_ensure_model``, which would deadlock on it.
        The model is read from ``self`` rather than passed in, so a caller that
        picked one up before a concurrent demotion cannot go on encoding — and
        pass a finite-check it no longer deserves — on the device ken just gave
        up on. ``self._model`` and ``self.device`` only ever move together,
        under this lock.
        """
        try:
            arr = self._run(self._model, payload)
            if self.device == "cpu" or self._looks_encoded(arr):
                return arr
            reason = "returned vectors that are not finite unit vectors"
        except Exception as exc:
            if self.device == "cpu":
                raise
            reason = f"raised ({exc})"
        logger.warning(
            "embedding on %s %s; using the CPU for the rest of this process",
            self.device, reason,
        )
        self._model = self._build("cpu")
        self.device = "cpu"
        return self._run(self._model, payload)

    def _encode(self, texts: list[str], prompt: str) -> list[np.ndarray]:
        self._ensure_model()  # builds outside the lock it takes itself
        payload = [prompt + t for t in texts] if prompt else texts
        with self._lock:
            arr = self._encode_guarded(payload)
            self._free_device_cache()
        return [np.asarray(v, dtype=np.float32) for v in arr]

    def _free_device_cache(self) -> None:
        # Release cached blocks between batches so a long reembed doesn't
        # accumulate fragmentation. This matters more on Apple Silicon than on
        # a discrete card: there the GPU allocator is eating the machine's only
        # RAM, so a cache ken never reuses is taken from everything else running.
        device = str(self.device)
        if not (device.startswith("cuda") or device.startswith("mps")):
            return
        try:
            import torch

            if device.startswith("cuda"):
                torch.cuda.empty_cache()
            elif device.startswith("mps"):
                # ``torch.mps`` exists in every build from 2.0 on, CUDA-only
                # Linux ones included — where the call *raises* rather than
                # no-ops. Reaching here means MPS is the live device so it
                # won't, but do not read the getattr as the safety net: it
                # only covers torch < 2.0. The try/except is what holds.
                empty = getattr(getattr(torch, "mps", None), "empty_cache", None)
                if empty is not None:
                    empty()
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
