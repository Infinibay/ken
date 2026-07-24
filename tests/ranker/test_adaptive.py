"""Phase 2: adaptive per-query similarity threshold unit tests."""

from __future__ import annotations

import numpy as np

from ken.ranker.channels import ADAPTIVE_FLOOR, _adaptive_threshold, adaptive_enabled


def test_adaptive_disabled_returns_fixed(monkeypatch):
    monkeypatch.delenv("KEN_RANKER_ADAPTIVE", raising=False)
    sims = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    assert _adaptive_threshold(sims, 0.40) == 0.40


def test_adaptive_only_lowers_never_raises(monkeypatch):
    monkeypatch.setenv("KEN_RANKER_ADAPTIVE", "1")
    # A strong-signal distribution whose μ+kσ exceeds the fixed floor must
    # not raise the threshold above the fixed floor.
    strong = np.array([0.5, 0.6, 0.7, 0.8], dtype=np.float32)
    assert _adaptive_threshold(strong, 0.40) == 0.40


def test_adaptive_lowers_for_weak_distribution(monkeypatch):
    monkeypatch.setenv("KEN_RANKER_ADAPTIVE", "1")
    # A weak, tight distribution (all low sims) lowers the threshold so the
    # relatively-best items can still surface.
    weak = np.array([0.20, 0.22, 0.24, 0.26], dtype=np.float32)
    thr = _adaptive_threshold(weak, 0.40)
    assert ADAPTIVE_FLOOR <= thr < 0.40


def test_adaptive_respects_floor(monkeypatch):
    monkeypatch.setenv("KEN_RANKER_ADAPTIVE", "1")
    flat = np.array([0.01, 0.01, 0.01], dtype=np.float32)
    assert _adaptive_threshold(flat, 0.40) == ADAPTIVE_FLOOR


def test_adaptive_enabled_flag(monkeypatch):
    monkeypatch.setenv("KEN_RANKER_ADAPTIVE", "on")
    assert adaptive_enabled() is True
    monkeypatch.setenv("KEN_RANKER_ADAPTIVE", "")
    assert adaptive_enabled() is False
