"""Remove ken's project wiring while preserving user-owned config.

Uninstall removes ken hook entries from Claude and Codex config, removes
ken MCP registrations, and optionally deletes `.ken/`. It deliberately
matches only ken-owned entries so user hooks, unrelated MCP servers, and
other project settings stay intact.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ken import _paths
from ken.codex_hooks_template import (
    remove_ken_codex_hooks,
    remove_ken_mcp_block,
    write_codex_hooks,
)
from ken.hooks_template import remove_ken_hooks, write_settings
from ken.install import (
    CLAUDE_SETTINGS,
    CODEX_CONFIG_FILE,
    CODEX_HOOKS_FILE,
    MCP_SETTINGS,
)
from ken.opencode_template import (
    read_opencode_jsonc,
    remove_ken_mcp_entry,
    write_opencode_json,
)


def _uninstall_opencode(root: Path) -> None:
    """Strip the ``mcp.ken`` entry from the project's opencode config.

    Same deal as the Claude/Codex paths: read, strip our key, write
    back if anything remains, delete the file if it is now empty. We
    also handle JSONC inputs (a user may have written comments above
    the block — we strip them, just as the install path would have).
    """
    for name in ("opencode.json", "opencode.jsonc"):
        config_p = root / name
        if not config_p.is_file():
            continue
        try:
            existing = read_opencode_jsonc(config_p)
        except json.JSONDecodeError as exc:
            print(f"[opencode] {name} is not valid JSON ({exc}); leaving alone")
            continue
        if not isinstance(existing, dict):
            continue
        cleaned = remove_ken_mcp_entry(existing)
        if cleaned == existing:
            print(f"[opencode] {name} had no ken entry — left alone")
            continue
        if cleaned:
            write_opencode_json(config_p, cleaned)
            print(f"[opencode] removed ken entry from {name}")
        else:
            config_p.unlink()
            print(f"[opencode] {name} now empty — deleted")


def uninstall(project_path: Path, *, keep_db: bool) -> int:
    root = project_path.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"no .ken project at {root}", file=sys.stderr)
        return 1

    settings_p = root / CLAUDE_SETTINGS
    if settings_p.is_file():
        try:
            existing = json.loads(settings_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        cleaned = remove_ken_hooks(existing)
        if cleaned:
            write_settings(settings_p, cleaned)
            print(f"[hooks] removed ken entries from {CLAUDE_SETTINGS}")
        else:
            settings_p.unlink()
            print(f"[hooks] {CLAUDE_SETTINGS} now empty — deleted")

    mcp_p = root / MCP_SETTINGS
    if mcp_p.is_file():
        try:
            mcp_existing = json.loads(mcp_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            mcp_existing = {}
        if (
            isinstance(mcp_existing.get("mcpServers"), dict)
            and "ken" in mcp_existing["mcpServers"]
        ):
            del mcp_existing["mcpServers"]["ken"]
            if mcp_existing["mcpServers"]:
                mcp_p.write_text(
                    json.dumps(mcp_existing, indent=2) + "\n", encoding="utf-8"
                )
                print(f"[mcp] removed ken entry from {MCP_SETTINGS}")
            else:
                mcp_p.unlink()
                print(f"[mcp] {MCP_SETTINGS} now empty — deleted")

    codex_hooks_p = root / CODEX_HOOKS_FILE
    if codex_hooks_p.is_file():
        try:
            existing = json.loads(codex_hooks_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        cleaned = remove_ken_codex_hooks(existing)
        if cleaned.get("hooks"):
            write_codex_hooks(codex_hooks_p, cleaned)
            print(f"[codex] removed ken entries from {CODEX_HOOKS_FILE}")
        else:
            codex_hooks_p.unlink()
            print(f"[codex] {CODEX_HOOKS_FILE} now empty — deleted")

    codex_cfg_p = root / CODEX_CONFIG_FILE
    if codex_cfg_p.is_file():
        cur = codex_cfg_p.read_text(encoding="utf-8")
        cleaned_text = remove_ken_mcp_block(cur)
        if cleaned_text != cur:
            if cleaned_text.strip():
                codex_cfg_p.write_text(cleaned_text, encoding="utf-8")
                print(f"[codex] removed ken MCP entry from {CODEX_CONFIG_FILE}")
            else:
                codex_cfg_p.unlink()
                print(f"[codex] {CODEX_CONFIG_FILE} now empty — deleted")

    _uninstall_opencode(root)

    if keep_db:
        print(f"[db] keeping .ken/ ({_paths.db_path(root)})")
    else:
        ken_dir = _paths.ken_dir(root)
        if ken_dir.is_dir():
            shutil.rmtree(ken_dir)
            print(f"[db] removed {ken_dir}")

    print(f"✓ ken uninstalled from {root}")
    return 0
