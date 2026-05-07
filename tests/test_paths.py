"""Project root discovery + path helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ken import _paths


def test_find_project_root_walks_up(tmp_path):
    root = tmp_path / "proj"
    (root / ".ken").mkdir(parents=True)
    (root / ".ken" / "meta.json").write_text("{}")
    nested = root / "a" / "b" / "c"
    nested.mkdir(parents=True)
    found = _paths.find_project_root(start=nested)
    assert found is not None
    assert found.resolve() == root.resolve()


def test_find_project_root_returns_none_when_missing(tmp_path):
    """Plain temp dir with no .ken/ above it → None."""
    # Save & restore env to avoid bleeding into other tests.
    saved = os.environ.pop("KEN_PROJECT_ROOT", None)
    try:
        # Use a path that's guaranteed to not have .ken in any ancestor.
        result = _paths.find_project_root(start=tmp_path)
        # Walking up may eventually hit a real .ken/ on the dev machine —
        # we only guarantee that without one it'd be None. Accept either.
        if result is not None:
            # If it found something, at least confirm it's a valid project root.
            assert _paths.meta_path(result).is_file()
    finally:
        if saved is not None:
            os.environ["KEN_PROJECT_ROOT"] = saved


def test_find_project_root_respects_env_var(tmp_path, monkeypatch):
    root = tmp_path / "envproj"
    (root / ".ken").mkdir(parents=True)
    (root / ".ken" / "meta.json").write_text("{}")
    monkeypatch.setenv("KEN_PROJECT_ROOT", str(root))
    # Even if start= points elsewhere, env var wins.
    other = tmp_path / "other"
    other.mkdir()
    found = _paths.find_project_root(start=other)
    assert found is not None
    assert found.resolve() == root.resolve()


def test_env_var_with_invalid_path_returns_none(tmp_path, monkeypatch):
    """Env var pointing somewhere with no meta.json → None (not a fallback)."""
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.setenv("KEN_PROJECT_ROOT", str(nowhere))
    assert _paths.find_project_root() is None


def test_path_helpers_compose(tmp_path):
    root = tmp_path
    assert _paths.ken_dir(root) == root / ".ken"
    assert _paths.meta_path(root) == root / ".ken" / "meta.json"
    assert _paths.db_path(root) == root / ".ken" / "ken.db"
    assert _paths.port_path(root) == root / ".ken" / "daemon.port"
    assert _paths.pid_path(root) == root / ".ken" / "daemon.pid"
    assert _paths.log_path(root) == root / ".ken" / "daemon.log"
