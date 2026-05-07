"""Codex-specific install wiring."""

from __future__ import annotations

import json
import stat

from pathlib import Path

from ken.indexer import IndexStats
from ken.install import _prioritize_embed_rels, _wire_codex, install
from ken.cli import main


def test_force_codex_writes_hooks_and_config(tmp_path):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    codex_dir.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        _wire_codex(tmp_path, verbose=False, force=True)
    finally:
        codex_dir.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)

    hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    config = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")

    assert "UserPromptSubmit" in hooks["hooks"]
    assert "[mcp_servers.ken]" in config
    assert codex_dir.stat().st_mode & stat.S_IWUSR


def test_force_codex_replaces_invalid_hooks_json(tmp_path):
    hooks_p = tmp_path / ".codex" / "hooks.json"
    hooks_p.parent.mkdir()
    hooks_p.write_text("{not json", encoding="utf-8")

    _wire_codex(tmp_path, verbose=False, force=True)

    hooks = json.loads(hooks_p.read_text(encoding="utf-8"))
    assert "SessionStart" in hooks["hooks"]


def test_install_cli_passes_agent_and_embed_flags(monkeypatch, tmp_path):
    calls = []

    def fake_install(path, *, verbose, force_claude, force_codex, embed, embed_limit):
        calls.append((path, verbose, force_claude, force_codex, embed, embed_limit))

    monkeypatch.setattr("ken.install.install", fake_install)

    rc = main(
        [
            "install",
            "--quiet",
            "--claude",
            "--codex",
            "--embed",
            "--embed-limit",
            "7",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert calls == [(tmp_path, False, True, True, True, 7)]


def test_prioritize_embed_rels_prefers_source_over_docs_and_tests():
    rels = [
        Path("docs/conf.py"),
        Path("tests/test_core.py"),
        Path("src/ken/core.py"),
        Path("README.md"),
        Path("src/ken/deep/module.py"),
    ]

    ordered = _prioritize_embed_rels(rels)

    assert ordered[:2] == [Path("src/ken/core.py"), Path("src/ken/deep/module.py")]
    assert ordered[-1] == Path("README.md")


def test_install_embed_limit_splits_eager_and_structural_index(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text("def core():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_core.py").write_text("def test_core():\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")

    monkeypatch.setattr("ken.install._wire_claude_hooks", lambda root, *, verbose: None)
    monkeypatch.setattr("ken.install._wire_mcp", lambda root, *, verbose: None)
    monkeypatch.setattr("ken.install._wire_codex", lambda root, *, verbose, force=False: None)

    class FakeEmbedder:
        pass

    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())
    calls = []

    def fake_index_files(conn, root, rels, *, on_progress, embedder):
        del conn, root, on_progress
        calls.append(([rel.as_posix() for rel in rels], embedder is not None))
        return IndexStats(visited=len(calls[-1][0]), parsed=len(calls[-1][0]))

    monkeypatch.setattr("ken.install.index_files", fake_index_files)

    install(tmp_path, verbose=False, embed=True, embed_limit=1)

    assert calls == [
        (["src/core.py"], True),
        (["README.md", "tests/test_core.py"], False),
    ]
