"""The oracle must retain working-tree code and reject silent source drift."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.rust_migration.reference import freeze_reference, reference_env, verify_reference


def source_repo(tmp_path):
    repo = tmp_path / "source"
    (repo / "src/ken").mkdir(parents=True)
    (repo / "src/ken/__init__.py").write_text("MARKER = 'frozen'\n")
    return repo


def manifest_for(repo, target):
    rows = [{"path": p.relative_to(repo).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (repo / "src").rglob("*.py")]
    target.write_text(json.dumps({"scope": ["src/ken/**"], "files": rows}))
    return target


def test_changed_deleted_and_added_legacy_files_are_reported(tmp_path):
    repo = source_repo(tmp_path)
    (repo / "src/ken/deleted.py").write_text("OLD = 1\n")
    manifest = manifest_for(repo, tmp_path / "baseline.json")
    assert verify_reference(repo, manifest) == []
    (repo / "src/ken/__init__.py").write_text("MARKER = 'changed'\n")
    (repo / "src/ken/deleted.py").unlink()
    (repo / "src/ken/added.py").write_text("NEW = 1\n")
    assert verify_reference(repo, manifest) == ["src/ken/__init__.py", "src/ken/added.py", "src/ken/deleted.py"]


def test_snapshot_keeps_untracked_source(tmp_path):
    repo = source_repo(tmp_path)
    (repo / "src/ken/new.py").write_bytes(b"VALUE = 7\n")
    frozen = freeze_reference(repo, tmp_path / "oracle")
    assert (frozen.root / "src/ken/new.py").read_bytes() == b"VALUE = 7\n"
    assert verify_reference(frozen.root, frozen.manifest_path) == []
    with pytest.raises(FileExistsError):
        freeze_reference(repo, frozen.root)


def test_snapshot_excludes_private_state(tmp_path):
    repo = source_repo(tmp_path)
    for name in [".env", ".ken/secret", ".git/config", ".venv/private"]:
        p = repo / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("private")
    outside = tmp_path / "private.txt"
    outside.write_text("secret")
    (repo / "src/ken/escape").symlink_to(outside)
    frozen = freeze_reference(repo, tmp_path / "oracle")
    for name in [".env", ".ken", ".git", ".venv", "src/ken/escape"]:
        assert not (frozen.root / name).exists()


def test_reference_imports_frozen_ken(tmp_path, monkeypatch):
    repo = source_repo(tmp_path)
    frozen = freeze_reference(repo, tmp_path / "oracle")
    (repo / "src/ken/__init__.py").write_text("MARKER = 'live'\n")
    for key in ["KEN_PROJECT_ROOT", "KEN_STATIC_HEAD", "HTTP_PROXY", "HTTPS_PROXY"]:
        monkeypatch.setenv(key, "inherited")
    env = reference_env(frozen, tmp_path / "sandbox")
    assert not any(k in env for k in ["KEN_PROJECT_ROOT", "KEN_STATIC_HEAD", "HTTP_PROXY", "HTTPS_PROXY"])
    result = subprocess.run([sys.executable, "-c", "import ken,json; print(json.dumps([ken.MARKER,ken.__file__]))"],
                            cwd=repo, env=env, capture_output=True, text=True, check=True)
    marker, path = json.loads(result.stdout)
    assert marker == "frozen"
    assert Path(path).is_relative_to(frozen.root)
