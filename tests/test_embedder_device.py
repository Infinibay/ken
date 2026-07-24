"""GPU-aware device selection + graceful CPU fallback in the embedder."""

from __future__ import annotations

import numpy as np
import pytest

from ken.embedder import onnx_fastembed as oe
from ken.embedder.onnx_fastembed import (
    OnnxEmbedder,
    _CPU_PROVIDER,
    _device_ids,
    _select_providers,
)


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
