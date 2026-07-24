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
