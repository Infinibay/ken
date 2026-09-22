"""Project-local MCP overlay for the official DeepSeek Harness (dsh)."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

DEEPSEEK_OVERLAY = ".dsh/ken.cordis.json"
PLUGIN = "@deepseek-ai/dsh-mcp-client"


def ken_entry(root: Path) -> dict:
    return {
        "id": "ken-mcp",
        "name": PLUGIN,
        "config": {
            "serverName": "ken",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-m", "ken", "mcp", str(root.resolve())],
            "cwd": str(root.resolve()),
        },
    }


def _is_ken(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("id") == "ken-mcp"
        and entry.get("name") == PLUGIN
    )


def _read_overlay(path: Path) -> list[dict]:
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"DeepSeek overlay must be a project-local file: {path}")
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(
        isinstance(patch, dict) for patch in value
    ):
        raise ValueError(f"Expected a Cordis patch list in {path}")
    for patch in value:
        if "insert" in patch and not isinstance(patch["insert"], list):
            raise ValueError(f"Expected an insert list in {path}")
    return value


def wire_deepseek(root: Path, *, verbose: bool) -> None:
    """Merge only Ken's row; the launcher explicitly selects this overlay."""
    path = root / DEEPSEEK_OVERLAY
    patches = _read_overlay(path)
    found = False
    for patch in patches:
        for row in patch.get("insert", []):
            if isinstance(row, dict) and row.get("id") == "ken-mcp":
                if found:
                    raise ValueError(f"Duplicate ken-mcp entries in {path}")
                if not _is_ken(row):
                    raise ValueError(f"Conflicting ken-mcp entry in {path}")
                config = row.get("config", {})
                if not isinstance(config, dict):
                    raise ValueError(f"Expected a config object in {path}")
                row["config"] = {**config, **ken_entry(root)["config"]}
                found = True
    if not found:
        patches.append({"insert": [ken_entry(root)]})
    content = json.dumps(patches, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The file is dedicated to this overlay, not a global Harness profile.
        path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"[deepseek] MCP overlay: {DEEPSEEK_OVERLAY}")


def unwire_deepseek(root: Path) -> None:
    path = root / DEEPSEEK_OVERLAY
    if not path.exists():
        return
    patches = _read_overlay(path)
    cleaned = []
    for patch in patches:
        if "insert" in patch:
            rows = [row for row in patch["insert"] if not _is_ken(row)]
            if rows:
                cleaned.append({**patch, "insert": rows})
            elif set(patch) != {"insert"}:
                cleaned.append(
                    {key: value for key, value in patch.items() if key != "insert"}
                )
        else:
            cleaned.append(patch)
    if cleaned == patches:
        return
    if cleaned:
        path.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink()


def launch_command(root: Path) -> str:
    return f"cd {shlex.quote(str(root))} && dsh --profile web --patch {shlex.quote(DEEPSEEK_OVERLAY)}"
