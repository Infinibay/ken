"""Shared test fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_ken_user_config(tmp_path, monkeypatch):
    """Point the user config at a fresh temp dir for every test.

    Without this, a developer's real ``~/.config/ken/config.json`` (e.g. a
    ``ken default-model`` override pointing at a torch-only model) would leak
    into the suite and break tests that build the real embedder.
    """
    monkeypatch.setenv("KEN_CONFIG_DIR", str(tmp_path / "ken-config"))
    # Same reasoning one layer down: ``recommended_model()`` prefers the static
    # table when its artifact is present, so a developer who has one cached
    # would silently run a different suite than CI does — and the difference
    # would show up as unrelated assertions about the recommended model
    # failing, which is a needlessly confusing way to learn about it. Tests that
    # want the table set KEN_STATIC_HEAD themselves.
    monkeypatch.setenv("KEN_CACHE_DIR", str(tmp_path / "ken-cache"))
    monkeypatch.delenv("KEN_STATIC_HEAD", raising=False)
