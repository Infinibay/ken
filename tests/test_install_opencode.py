"""OpenCode-specific install wiring.

Mirrors ``test_install_codex.py`` for the OpenCode path: the install /
uninstall pair leaves ``opencode.json`` (or ``opencode.jsonc``) in a
shape opencode accepts, idempotent across re-runs, and tolerant of an
existing user-authored config (sibling MCP servers, model overrides,
JSONC comments).
"""

from __future__ import annotations

import contextlib
import io
import json

import pytest

from ken.cli import main
from ken.install import (
    OPENCODE_CONFIG_FILES,
    _detect_agent_wiring,
    _wire_opencode,
    install,
)
from ken.install_uninstall import _uninstall_opencode, uninstall
from ken.opencode_template import (
    KEN_OPENCODE_MCP_ENTRY,
    merge_opencode_config,
    read_opencode_jsonc,
    remove_ken_mcp_entry,
)


def test_merge_into_empty_config_creates_mcp_ken():
    merged, touched = merge_opencode_config(None)
    assert touched is True
    assert merged == {"mcp": {"ken": KEN_OPENCODE_MCP_ENTRY}}


def test_merge_into_existing_config_preserves_siblings():
    existing = {
        "$schema": "https://opencode.ai/config.json",
        "model": "anthropic/claude-sonnet-4-5",
        "agent": {"plan": {"prompt": "plan mode"}},
    }
    merged, touched = merge_opencode_config(existing)
    assert touched is True
    assert merged["model"] == "anthropic/claude-sonnet-4-5"
    assert merged["agent"]["plan"]["prompt"] == "plan mode"
    assert merged["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY


def test_merge_is_idempotent():
    _merged, touched = merge_opencode_config({"mcp": {"ken": KEN_OPENCODE_MCP_ENTRY}})
    assert touched is False


def test_remove_ken_mcp_entry_drops_only_ken_block():
    cfg = {
        "model": "anthropic/claude-sonnet-4-5",
        "mcp": {
            "ken": KEN_OPENCODE_MCP_ENTRY,
            "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp"},
        },
    }
    cleaned = remove_ken_mcp_entry(cfg)
    assert "ken" not in cleaned["mcp"]
    assert cleaned["mcp"]["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert cleaned["model"] == "anthropic/claude-sonnet-4-5"


def test_remove_ken_mcp_entry_drops_empty_mcp_section():
    cfg = {"mcp": {"ken": KEN_OPENCODE_MCP_ENTRY}}
    cleaned = remove_ken_mcp_entry(cfg)
    assert "mcp" not in cleaned


def test_read_opencode_jsonc_strips_comments_without_touching_strings(tmp_path):
    p = tmp_path / "opencode.jsonc"
    p.write_text(
        """// top-level
{
  /* block */
  "model": "anthropic/claude-sonnet-4-5",
  "mcp": {
    // a URL containing // must NOT be eaten
    "other": {"type": "remote", "url": "https://example.com/path"},
  },
  "agent": {"plan": {"prompt": "be careful with /* nested */ and // slashes"}},
}
""",
        encoding="utf-8",
    )
    parsed = read_opencode_jsonc(p)
    assert parsed is not None
    assert parsed["model"] == "anthropic/claude-sonnet-4-5"
    assert parsed["mcp"]["other"]["url"] == "https://example.com/path"
    assert (
        parsed["agent"]["plan"]["prompt"]
        == "be careful with /* nested */ and // slashes"
    )


def test_read_opencode_jsonc_returns_none_for_missing(tmp_path):
    assert read_opencode_jsonc(tmp_path / "nope.json") is None


def test_wire_opencode_creates_opencode_json_when_missing(tmp_path):
    _wire_opencode(tmp_path, verbose=False)
    cfg = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY


def test_wire_opencode_merges_into_existing_json(tmp_path):
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "anthropic/claude-sonnet-4-5",
                "agent": {"plan": {"prompt": "plan mode"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _wire_opencode(tmp_path, verbose=False)
    cfg = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["model"] == "anthropic/claude-sonnet-4-5"
    assert cfg["agent"]["plan"]["prompt"] == "plan mode"
    assert cfg["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY


def test_wire_opencode_honours_existing_jsonc(tmp_path):
    (tmp_path / "opencode.jsonc").write_text(
        """// user-authored
{
  "model": "anthropic/claude-sonnet-4-5",
  "mcp": {
    "context7": { "type": "remote", "url": "https://mcp.context7.com/mcp" },
  },
}
""",
        encoding="utf-8",
    )
    _wire_opencode(tmp_path, verbose=False)
    cfg = json.loads((tmp_path / "opencode.jsonc").read_text(encoding="utf-8"))
    assert cfg["mcp"]["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert cfg["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY


def test_wire_opencode_is_idempotent(tmp_path):
    _wire_opencode(tmp_path, verbose=False)
    first = (tmp_path / "opencode.json").read_text(encoding="utf-8")
    _wire_opencode(tmp_path, verbose=False)
    second = (tmp_path / "opencode.json").read_text(encoding="utf-8")
    assert first == second


def test_wire_opencode_leaves_both_files_alone_when_both_exist(tmp_path, capsys):
    (tmp_path / "opencode.json").write_text('{"model": "x"}\n', encoding="utf-8")
    (tmp_path / "opencode.jsonc").write_text(
        '// hi\n{"model": "y"}\n', encoding="utf-8"
    )
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        _wire_opencode(tmp_path, verbose=False)
    a = (tmp_path / "opencode.json").read_text(encoding="utf-8")
    b = (tmp_path / "opencode.jsonc").read_text(encoding="utf-8")
    assert a == '{"model": "x"}\n'
    assert b == '// hi\n{"model": "y"}\n'
    assert "leaving them alone" in buf.getvalue()


def test_detect_agent_wiring_picks_opencode_marker(tmp_path):
    (tmp_path / "opencode.json").write_text("{}\n", encoding="utf-8")
    _, _, use_opencode = _detect_agent_wiring(
        tmp_path, force_claude=False, force_codex=False
    )
    assert use_opencode is True


def test_detect_agent_wiring_picks_opencode_dir_with_content(tmp_path):
    (tmp_path / ".opencode" / "agents").mkdir(parents=True)
    (tmp_path / ".opencode" / "agents" / "x.md").write_text("# x\n", encoding="utf-8")
    _, _, use_opencode = _detect_agent_wiring(
        tmp_path, force_claude=False, force_codex=False
    )
    assert use_opencode is True


def test_detect_agent_wiring_ignores_empty_opencode_dir(tmp_path):
    (tmp_path / ".opencode").mkdir()
    _, _, use_opencode = _detect_agent_wiring(
        tmp_path, force_claude=False, force_codex=False
    )
    assert use_opencode is False


def test_detect_agent_wiring_force_opencode_overrides(tmp_path):
    _, _, use_opencode = _detect_agent_wiring(
        tmp_path, force_claude=False, force_codex=False, force_opencode=True
    )
    assert use_opencode is True


def test_install_force_opencode_wires_and_indexes(tmp_path):
    result = install(tmp_path, verbose=False, force_opencode=True, no_wire=False)
    assert (tmp_path / "opencode.json").is_file()
    cfg = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY
    assert result.project_root == tmp_path


def test_install_no_wire_skips_opencode(tmp_path):
    install(tmp_path, verbose=False, no_wire=True)
    assert not (tmp_path / "opencode.json").exists()


def test_install_autodetects_opencode_via_existing_config(tmp_path):
    (tmp_path / "opencode.json").write_text(
        json.dumps({"model": "anthropic/claude-sonnet-4-5"}, indent=2) + "\n",
        encoding="utf-8",
    )
    install(tmp_path, verbose=False, no_wire=False)
    cfg = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["model"] == "anthropic/claude-sonnet-4-5"
    assert cfg["mcp"]["ken"]["type"] == "local"


def test_install_combines_with_claude_when_forced(tmp_path):
    install(
        tmp_path, verbose=False, force_claude=True, force_opencode=True, no_wire=False
    )
    assert (tmp_path / ".mcp.json").is_file()
    assert (tmp_path / "opencode.json").is_file()


def test_uninstall_opencode_removes_ken_entry_keeps_sibling(tmp_path):
    cfg = {
        "model": "anthropic/claude-sonnet-4-5",
        "mcp": {
            "ken": KEN_OPENCODE_MCP_ENTRY,
            "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp"},
        },
    }
    (tmp_path / "opencode.json").write_text(
        json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
    )
    _uninstall_opencode(tmp_path)
    after = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert after == {
        "model": "anthropic/claude-sonnet-4-5",
        "mcp": {"context7": {"type": "remote", "url": "https://mcp.context7.com/mcp"}},
    }


def test_uninstall_opencode_deletes_empty_file(tmp_path):
    (tmp_path / "opencode.json").write_text(
        json.dumps({"mcp": {"ken": KEN_OPENCODE_MCP_ENTRY}}, indent=2) + "\n",
        encoding="utf-8",
    )
    _uninstall_opencode(tmp_path)
    assert not (tmp_path / "opencode.json").exists()


def test_uninstall_opencode_handles_jsonc(tmp_path):
    (tmp_path / "opencode.jsonc").write_text(
        json.dumps({"model": "anthropic/claude-sonnet-4-5"}, indent=2) + "\n",
        encoding="utf-8",
    )
    install(tmp_path, verbose=False, force_opencode=True, no_wire=False)
    assert (tmp_path / "opencode.jsonc").is_file()
    uninstall(tmp_path, keep_db=False)
    cfg = json.loads((tmp_path / "opencode.jsonc").read_text(encoding="utf-8"))
    assert cfg == {"model": "anthropic/claude-sonnet-4-5"}


def test_cli_install_accepts_opencode_flag(tmp_path, capsys):
    rc = main(["install", str(tmp_path), "--opencode", "-q"])
    assert rc == 0
    assert (tmp_path / "opencode.json").is_file()
    cfg = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert cfg["mcp"]["ken"] == KEN_OPENCODE_MCP_ENTRY


def test_cli_help_mentions_opencode_flag(capsys):
    with pytest.raises(SystemExit):
        main(["install", "--help"])
    out = capsys.readouterr().out
    assert "--opencode" in out


def test_opencode_config_files_are_canonical_names():
    assert OPENCODE_CONFIG_FILES == ("opencode.json", "opencode.jsonc")
