"""GPU-aware device selection + graceful CPU fallback in the embedder.

Covers both backends. The ONNX one picks execution providers; the torch one
picks a torch device string and, on Apple Silicon, has to survive a GPU that
fails *quietly*. Neither torch nor a GPU is installed in CI, so the torch tests
drive fakes — the logic under test is ken's, not the vendor's.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from ken.embedder import onnx_fastembed as oe
from ken.embedder import st_backend as stb
from ken.embedder.onnx_fastembed import (
    OnnxEmbedder,
    _CPU_PROVIDER,
    _device_ids,
    _select_providers,
)
from ken.embedder.st_backend import SentenceTransformerEmbedder, _resolve_device


def test_cpu_pref_never_touches_gpu(monkeypatch):
    # Even with a GPU provider reported, an explicit cpu pref stays on CPU.
    monkeypatch.setattr(oe, "_available_providers", lambda: {"CUDAExecutionProvider", _CPU_PROVIDER})
    assert _select_providers("cpu") == ([_CPU_PROVIDER], "cpu")


def test_auto_prefers_gpu_when_available(monkeypatch):
    monkeypatch.setattr(oe, "_available_providers", lambda: {"CUDAExecutionProvider", _CPU_PROVIDER})
    providers, device = _select_providers("auto")
    assert device == "gpu"
    assert providers == ["CUDAExecutionProvider", _CPU_PROVIDER]  # CPU kept as last fallback


def test_auto_falls_back_to_cpu_when_no_gpu(monkeypatch):
    monkeypatch.setattr(oe, "_available_providers", lambda: {"AzureExecutionProvider", _CPU_PROVIDER})
    assert _select_providers("auto") == ([_CPU_PROVIDER], "cpu")


def test_rocm_is_recognised_as_gpu(monkeypatch):
    monkeypatch.setattr(oe, "_available_providers", lambda: {"ROCMExecutionProvider", _CPU_PROVIDER})
    providers, device = _select_providers("gpu")
    assert device == "gpu"
    assert providers[0] == "ROCMExecutionProvider"
    assert providers[-1] == _CPU_PROVIDER


def test_device_ids_parsing(monkeypatch):
    monkeypatch.setenv("KEN_EMBED_DEVICE_ID", "0,1")
    assert _device_ids() == [0, 1]
    monkeypatch.setenv("KEN_EMBED_DEVICE_ID", "  ")
    assert _device_ids() is None
    monkeypatch.setenv("KEN_EMBED_DEVICE_ID", "notanint")
    assert _device_ids() is None


def test_device_pref_normalisation(monkeypatch):
    monkeypatch.delenv("KEN_EMBED_DEVICE", raising=False)
    assert OnnxEmbedder()._device_pref == "auto"
    assert OnnxEmbedder(device="CUDA")._device_pref == "gpu"
    assert OnnxEmbedder(device="gpu")._device_pref == "gpu"
    assert OnnxEmbedder(device="cpu")._device_pref == "cpu"
    monkeypatch.setenv("KEN_EMBED_DEVICE", "cpu")
    assert OnnxEmbedder()._device_pref == "cpu"


def test_gpu_init_failure_falls_back_to_cpu(monkeypatch):
    """A GPU provider is present but building on it raises (driver mismatch):
    the embedder must rebuild on CPU rather than propagate the error."""
    monkeypatch.setattr(oe, "_available_providers", lambda: {"CUDAExecutionProvider", _CPU_PROVIDER})

    class FakeModel:
        def embed(self, texts):
            for _ in texts:
                yield np.ones(4, dtype=np.float32)

    built_with: list[list[str]] = []

    def fake_build(self, providers):
        built_with.append(list(providers))
        if any("CUDA" in p or "ROCM" in p or "Tensorrt" in p for p in providers):
            raise RuntimeError("libcudart.so.12: cannot open shared object file")
        return FakeModel()

    monkeypatch.setattr(OnnxEmbedder, "_build", fake_build, raising=True)
    emb = OnnxEmbedder(device="auto")
    vec = emb.embed_query("hola mundo")

    assert emb.device == "cpu"                    # fell back
    assert vec.shape == (4,)                      # and still produced a vector
    assert built_with[0][0] == "CUDAExecutionProvider"   # tried GPU first
    assert built_with[-1] == [_CPU_PROVIDER]             # then CPU


def test_cpu_build_error_is_not_swallowed(monkeypatch):
    """If even the CPU build fails, that error propagates (no infinite mask)."""
    monkeypatch.setattr(oe, "_available_providers", lambda: {_CPU_PROVIDER})

    def boom(self, providers):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(OnnxEmbedder, "_build", boom, raising=True)
    with pytest.raises(RuntimeError, match="model download failed"):
        OnnxEmbedder(device="cpu").embed_query("x")


# ── torch backend: device resolution (incl. Apple Silicon / MPS) ──────


def _fake_torch(*, cuda: bool = False, mps: bool | None = False, version: str = "2.9.0"):
    """Stand-in for the torch module.

    ``mps=None`` models a torch build old enough to have no MPS backend at all,
    where ``torch.backends.mps`` does not exist.
    """
    backends = SimpleNamespace()
    if mps is not None:
        backends.mps = SimpleNamespace(is_available=lambda: mps)
    return SimpleNamespace(
        __version__=version,
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=backends,
    )


@pytest.fixture
def torch_env(monkeypatch):
    """Install a fake torch and clear the device env vars."""
    monkeypatch.delenv("KEN_EMBED_DEVICE", raising=False)
    monkeypatch.delenv("KEN_EMBED_DEVICE_ID", raising=False)

    def install(**kwargs):
        monkeypatch.setitem(sys.modules, "torch", _fake_torch(**kwargs))

    return install


def test_auto_uses_apple_silicon_gpu(torch_env):
    torch_env(cuda=False, mps=True)
    assert _resolve_device() == "mps"


def test_cuda_is_preferred_over_mps_when_both_exist(torch_env):
    torch_env(cuda=True, mps=True)
    assert _resolve_device() == "cuda"


def test_auto_falls_back_to_cpu_with_no_accelerator(torch_env):
    torch_env(cuda=False, mps=False)
    assert _resolve_device() == "cpu"


def test_cpu_pref_ignores_an_available_mps(torch_env, monkeypatch):
    torch_env(cuda=False, mps=True)
    monkeypatch.setenv("KEN_EMBED_DEVICE", "cpu")
    assert _resolve_device() == "cpu"


def test_pinning_cuda_does_not_silently_substitute_mps(torch_env, monkeypatch):
    """Someone who asks for CUDA on a Mac gets the CPU, not the other GPU —
    pinning a device is usually a comparison, and a swap would corrupt it."""
    torch_env(cuda=False, mps=True)
    monkeypatch.setenv("KEN_EMBED_DEVICE", "cuda")
    assert _resolve_device() == "cpu"


def test_pinning_mps_falls_back_to_cpu_when_absent(torch_env, monkeypatch):
    torch_env(cuda=True, mps=False)
    monkeypatch.setenv("KEN_EMBED_DEVICE", "mps")
    assert _resolve_device() == "cpu"


def test_gpu_pref_reaches_mps(torch_env, monkeypatch):
    torch_env(cuda=False, mps=True)
    monkeypatch.setenv("KEN_EMBED_DEVICE", "gpu")
    assert _resolve_device() == "mps"


def test_torch_without_an_mps_backend_is_not_an_error(torch_env):
    torch_env(cuda=False, mps=None)  # torch too old to have torch.backends.mps
    assert _resolve_device() == "cpu"


def test_device_id_selects_a_cuda_index(torch_env, monkeypatch):
    torch_env(cuda=True, mps=False)
    monkeypatch.setenv("KEN_EMBED_DEVICE_ID", "1")
    assert _resolve_device() == "cuda:1"
    monkeypatch.setenv("KEN_EMBED_DEVICE_ID", "notanint")
    assert _resolve_device() == "cuda"


def test_missing_torch_resolves_to_cpu(monkeypatch):
    monkeypatch.delenv("KEN_EMBED_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise
    assert _resolve_device() == "cpu"


def test_old_torch_is_refused_on_mps(torch_env):
    """torch < 2.9 could return finite, unit-norm, *wrong* vectors on MPS —
    the one failure the runtime guards cannot see. Exclude it by version."""
    torch_env(cuda=False, mps=True, version="2.8.0")
    assert _resolve_device() == "cpu"


def test_new_enough_torch_is_allowed_on_mps(torch_env):
    torch_env(cuda=False, mps=True, version="2.10.0.dev20260101")
    assert _resolve_device() == "mps"


def test_unparseable_torch_version_does_not_block_mps(torch_env):
    """A version string we failed to read is not evidence of the bug."""
    torch_env(cuda=False, mps=True, version="weird-vendor-build")
    assert _resolve_device() == "mps"


# ── torch backend: an accelerator that fails must not poison the index ──


_UNIT = np.full((1, 4), 0.5, dtype=np.float32)  # norm 1.0, as encode() promises


class _FakeST:
    """Minimal SentenceTransformer: healthy on CPU, configurable elsewhere."""

    def __init__(self, device: str, mode: str) -> None:
        self.device = device
        self._mode = mode

    def encode(self, payload, **_kwargs):
        n = len(payload)
        if self.device != "cpu":
            if self._mode == "nan":
                return np.full((n, 4), np.nan, dtype=np.float32)
            if self._mode == "zeros":
                # Finite, and what an unfilled GPU buffer survives
                # normalisation as — F.normalize clamps the divisor.
                return np.zeros((n, 4), dtype=np.float32)
            if self._mode == "bf16":
                # A *healthy* accelerator, in the precision one actually runs
                # in. sentence-transformers loads a checkpoint in its native
                # dtype, so Qwen3-Embedding is bfloat16 on CUDA, and a bf16
                # unit vector's norm lands a few parts in a thousand off. These
                # numbers are the ones measured on an RTX A5000.
                return np.repeat(_UNIT * 1.003458, n, axis=0).astype(np.float32)
            if self._mode == "raise":
                raise RuntimeError(
                    "The operator 'aten::_foo' is not currently implemented "
                    "for the MPS device."
                )
        return np.repeat(_UNIT, n, axis=0)

    def get_sentence_embedding_dimension(self):
        return 4


def _embedder_on(monkeypatch, device: str, mode: str):
    """A torch-backend embedder pinned to *device*, backed by _FakeST."""
    built: list[str] = []

    def fake_build(self, dev):
        built.append(dev)
        return _FakeST(dev, mode)

    monkeypatch.setattr(SentenceTransformerEmbedder, "_build", fake_build, raising=True)
    emb = SentenceTransformerEmbedder("Qwen/Qwen3-Embedding-0.6B", device=device)
    return emb, built


def test_mps_returning_nan_demotes_to_cpu(monkeypatch):
    """The dangerous failure: MPS answers with NaN instead of raising. Those
    vectors would be written to the DB and score against nothing, so the batch
    has to be redone on the CPU."""
    emb, built = _embedder_on(monkeypatch, "mps", "nan")
    vecs = emb.embed_passages(["hola mundo"])

    assert emb.device == "cpu"
    assert built == ["mps", "cpu"]
    assert np.isfinite(vecs[0]).all()


def test_mps_returning_all_zeros_demotes_to_cpu(monkeypatch):
    """The quietest failure: a row the GPU never filled in. It is finite, so an
    is-finite check waves it through, and it then scores 0.0 against every
    query for the life of the index. Only the unit-norm check catches it."""
    emb, built = _embedder_on(monkeypatch, "mps", "zeros")
    vecs = emb.embed_passages(["hola mundo"])

    assert emb.device == "cpu"
    assert built == ["mps", "cpu"]
    assert np.linalg.norm(vecs[0]) == pytest.approx(1.0)


def test_bfloat16_precision_does_not_demote(monkeypatch):
    """A healthy GPU running the checkpoint's own bfloat16 must be kept.

    This is the regression that mattered most in practice: sentence-transformers
    loads Qwen3-Embedding in bf16 on CUDA, whose ~8-bit mantissa leaves a
    normalised vector's norm off by ~3.5e-3 (measured on an RTX A5000). Against
    the old 1e-3 tolerance that fired on the very first batch, so *every* ken
    user with a GPU was silently demoted to the CPU with correct vectors in hand.
    """
    emb, built = _embedder_on(monkeypatch, "cuda", "bf16")
    vecs = emb.embed_passages(["hola mundo"])

    assert emb.device == "cuda", "a healthy bf16 GPU must not be demoted"
    assert built == ["cuda"], "no CPU rebuild should have happened"
    # …and what it hands back is exactly unit regardless of the device's dtype.
    assert np.linalg.norm(vecs[0]) == pytest.approx(1.0, abs=1e-6)


def test_returned_vectors_are_exactly_unit_on_cpu(monkeypatch):
    """The float32 re-normalise applies everywhere, so the bytes written to the
    index do not depend on which device built them."""
    emb, _ = _embedder_on(monkeypatch, "cpu", "healthy")
    vecs = emb.embed_passages(["uno", "dos"])

    assert len(vecs) == 2
    for v in vecs:
        assert np.linalg.norm(v) == pytest.approx(1.0, abs=1e-6)
        assert v.dtype == np.float32


def test_mps_raising_demotes_to_cpu(monkeypatch):
    emb, built = _embedder_on(monkeypatch, "mps", "raise")
    vecs = emb.embed_passages(["hola mundo"])

    assert emb.device == "cpu"
    assert built == ["mps", "cpu"]
    assert np.isfinite(vecs[0]).all()


def test_demotion_happens_once_not_per_batch(monkeypatch):
    emb, built = _embedder_on(monkeypatch, "mps", "nan")
    emb.embed_passages(["uno"])
    emb.embed_passages(["dos"])
    emb.embed_query("tres")

    assert built == ["mps", "cpu"]  # not rebuilt on every call


def test_encode_reads_the_current_model_not_a_caller_held_one(monkeypatch):
    """Two threads can be inside _encode at once. The second must not keep
    encoding on the device the first already abandoned — so the guard takes no
    model argument and reads self._model under the lock."""
    emb, _ = _embedder_on(monkeypatch, "mps", "nan")
    emb.embed_passages(["uno"])  # demotes; self._model is now the CPU one

    assert np.isfinite(emb._encode_guarded(["dos"])).all()


def test_cpu_failures_still_propagate(monkeypatch):
    """The guard exists to distrust accelerators, not to swallow real errors."""
    emb, _ = _embedder_on(monkeypatch, "cpu", "raise")

    def boom(payload, **_kwargs):
        raise RuntimeError("tokenizer exploded")

    emb._ensure_model().encode = boom
    with pytest.raises(RuntimeError, match="tokenizer exploded"):
        emb.embed_query("x")


def test_load_failure_on_mps_falls_back_to_cpu(monkeypatch):
    """Failing at *load* time (not encode time) also lands on the CPU."""
    built: list[str] = []

    def fake_build(self, dev):
        built.append(dev)
        if dev != "cpu":
            raise RuntimeError("MPS backend out of memory")
        return _FakeST(dev, "ok")

    monkeypatch.setattr(SentenceTransformerEmbedder, "_build", fake_build, raising=True)
    emb = SentenceTransformerEmbedder("Qwen/Qwen3-Embedding-0.6B", device="mps")
    vec = emb.embed_query("hola")

    assert emb.device == "cpu"
    assert built == ["mps", "cpu"]
    assert vec.shape == (4,)


def test_mps_build_caps_process_memory(monkeypatch):
    """Without the cap the MPS allocator's ceiling sits above physical RAM, so
    an oversized batch never raises — macOS just swaps. The cap is what turns
    it into the error the demote path already handles."""
    capped: list[float] = []
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(mps=SimpleNamespace(set_per_process_memory_fraction=capped.append)),
    )
    monkeypatch.setenv("KEN_MPS_MEMORY_FRACTION", "0.5")
    emb = SentenceTransformerEmbedder("Qwen/Qwen3-Embedding-0.6B")
    emb._cap_mps_memory()

    assert capped == [0.5]


def test_mps_memory_cap_failure_is_not_fatal(monkeypatch):
    """Every torch.mps entry point raises on a build without the backend, so
    a failed cap must never stop ken from embedding."""

    def boom(_frac):
        raise RuntimeError("Cannot execute setMemoryFraction() without MPS backend")

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(mps=SimpleNamespace(set_per_process_memory_fraction=boom)),
    )
    SentenceTransformerEmbedder("Qwen/Qwen3-Embedding-0.6B")._cap_mps_memory()  # no raise


def test_free_device_cache_is_a_noop_without_torch(monkeypatch):
    """A CPU-only install has no torch cache to drop and must not raise."""
    emb, _ = _embedder_on(monkeypatch, "cpu", "ok")
    emb.embed_query("x")
    emb.device = "mps"  # pretend, with torch absent
    monkeypatch.setitem(sys.modules, "torch", None)
    emb._free_device_cache()  # must not raise
