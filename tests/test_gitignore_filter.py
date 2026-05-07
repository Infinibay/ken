"""gitignore-aware project tree walk."""

from __future__ import annotations

from pathlib import Path

from ken.gitignore_filter import iter_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def test_iter_files_respects_root_gitignore(tmp_path):
    _touch(tmp_path / "a.py")
    _touch(tmp_path / "secret.env")
    _touch(tmp_path / "src" / "b.py")
    (tmp_path / ".gitignore").write_text("*.env\n")
    rels = sorted(p.as_posix() for p in iter_files(tmp_path))
    assert "a.py" in rels
    assert "src/b.py" in rels
    assert "secret.env" not in rels
    # .gitignore itself is NOT ignored (it's not in ALWAYS_IGNORE).
    assert ".gitignore" in rels


def test_iter_files_skips_always_ignore(tmp_path):
    """Built-in patterns: .ken/, .git/, node_modules/, __pycache__/, etc."""
    _touch(tmp_path / "good.py")
    _touch(tmp_path / ".ken" / "ken.db")
    _touch(tmp_path / ".git" / "HEAD")
    _touch(tmp_path / "node_modules" / "x" / "y.js")
    _touch(tmp_path / "__pycache__" / "x.pyc")
    rels = {p.as_posix() for p in iter_files(tmp_path)}
    assert "good.py" in rels
    assert all(not r.startswith(".ken/") for r in rels)
    assert all(not r.startswith(".git/") for r in rels)
    assert all(not r.startswith("node_modules/") for r in rels)
    assert all(not r.startswith("__pycache__/") for r in rels)


def test_iter_files_works_without_gitignore(tmp_path):
    """No .gitignore → just the ALWAYS_IGNORE set applies."""
    _touch(tmp_path / "a.py")
    _touch(tmp_path / "b.py")
    rels = {p.as_posix() for p in iter_files(tmp_path)}
    assert rels == {"a.py", "b.py"}


def test_iter_files_yields_only_files_not_directories(tmp_path):
    _touch(tmp_path / "src" / "a.py")
    rels = list(iter_files(tmp_path))
    # Each entry is a file; no directory entries.
    for r in rels:
        full = tmp_path / r
        assert full.is_file()


def test_iter_files_skips_pyc_via_glob_pattern(tmp_path):
    _touch(tmp_path / "x.py")
    _touch(tmp_path / "x.pyc")
    rels = {p.as_posix() for p in iter_files(tmp_path)}
    assert "x.py" in rels
    assert "x.pyc" not in rels
