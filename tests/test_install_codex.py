"""Codex-specific install wiring."""

from __future__ import annotations

import json
import stat

from ken.install import _wire_codex
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

    def fake_install(path, *, verbose, force_claude, force_codex, embed):
        calls.append((path, verbose, force_claude, force_codex, embed))

    monkeypatch.setattr("ken.install.install", fake_install)

    rc = main(["install", "--quiet", "--claude", "--codex", "--embed", str(tmp_path)])

    assert rc == 0
    assert calls == [(tmp_path, False, True, True, True)]
