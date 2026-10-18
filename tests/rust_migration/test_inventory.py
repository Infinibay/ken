"""Public interfaces and every source owner must survive inventory capture."""
import sys
from pathlib import Path

import pytest

from tools.rust_migration.inventory import audit_ownership, capture_cli, capture_mcp, source_owners
from tools.rust_migration.reference import Reference

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def reference():
    return Reference(ROOT, ROOT / "docs/validation/rust-migration-2026-10-18/baseline.json", "test", Path(sys.executable))


def test_nested_cli_defaults_are_captured(reference):
    routes = {tuple(row["command"]): row for row in capture_cli(reference)["routes"]}
    status = {p["dest"]: p for p in routes[("status",)]["options"]}
    assert status["path"]["default"] == "."
    assert status["json"]["default"] is False
    tool = {p["dest"]: p for p in routes[("hook", "tool-call")]["options"]}
    assert tool["phase"]["required"] is True
    assert tool["phase"]["choices"] == ["pre", "post"]
    assert ("tools", "ken_find") in routes


def test_mcp_schema_keeps_output_format(reference, tmp_path):
    result = capture_mcp(reference, tmp_path)
    tools = {t["name"]: t for t in result["tools"]}
    assert result["transport"] == "stdio"
    assert set(tools) == set(result["local_tools"])
    prop = tools["ken_find"]["inputSchema"]["properties"]["output_format"]
    assert prop["enum"] == ["compact", "json"]
    assert prop["default"] == "compact"


def test_unassigned_or_duplicate_sources_fail_inventory(reference):
    rows = source_owners(reference)
    assert audit_ownership(reference, rows) == []
    assert audit_ownership(reference, rows[:-1])
    assert audit_ownership(reference, rows + rows[:1])
