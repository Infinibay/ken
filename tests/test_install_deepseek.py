"""Official DeepSeek Harness uses an explicit project-local Cordis overlay."""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

from ken.cli import main
from ken.deepseek_template import (
    DEEPSEEK_OVERLAY,
    ken_entry,
    unwire_deepseek,
    wire_deepseek,
)
from ken.install import _detect_agent_wiring


def test_install_wires_project_and_explains_launcher_even_when_quiet(tmp_path, capsys):
    assert main(["install", str(tmp_path), "--deepseek", "--quiet"]) == 0
    patches = json.loads((tmp_path / DEEPSEEK_OVERLAY).read_text())
    config = patches[0]["insert"][0]["config"]
    assert config["command"] == sys.executable
    assert config["args"] == ["-m", "ken", "mcp", str(tmp_path.resolve())]
    assert config["cwd"] == str(tmp_path.resolve())
    assert "--patch .dsh/ken.cordis.json" in capsys.readouterr().out
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".codex").exists()
    assert _detect_agent_wiring(tmp_path, force_claude=False, force_codex=False) == (
        False,
        False,
        False,
        True,
    )


def test_merge_is_idempotent_preserving_other_patches_and_extra_options(tmp_path):
    path = tmp_path / DEEPSEEK_OVERLAY
    path.parent.mkdir()
    sibling = {"id": "other", "name": "unrelated-plugin"}
    entry = ken_entry(tmp_path)
    entry["config"]["toolCallTimeoutMs"] = 12345
    patches = [{"insert": [entry, sibling]}, {"id": "other", "disabled": True}]
    path.write_text(json.dumps(patches))
    wire_deepseek(tmp_path, verbose=False)
    first = path.read_bytes()
    wire_deepseek(tmp_path, verbose=False)
    assert path.read_bytes() == first
    assert json.loads(first) == patches
    unwire_deepseek(tmp_path)
    assert json.loads(path.read_text()) == [{"insert": [sibling]}, patches[1]]


def test_unwire_removes_dedicated_overlay(tmp_path):
    wire_deepseek(tmp_path, verbose=False)
    unwire_deepseek(tmp_path)
    assert not (tmp_path / DEEPSEEK_OVERLAY).exists()


def test_generated_stdio_command_discovers_and_calls_ken(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    (tmp_path / "sample.py").write_text("CACHE_DIR = 'cache'\n")
    main(["install", str(tmp_path), "--deepseek", "--quiet"])
    config = json.loads((tmp_path / DEEPSEEK_OVERLAY).read_text())[0]["insert"][0][
        "config"
    ]

    async def scenario(errlog):
        params = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            cwd=config["cwd"],
            env={"HF_HUB_OFFLINE": "1"},
        )
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write, read_timeout_seconds=15) as session,
        ):
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert {
                "ken_find",
                "ken_who",
                "ken_rule",
                "ken_check",
                "ken_recall",
            } <= names
            response = (
                await session.call_tool(
                    "ken_find",
                    {
                        "query": "CACHE_DIR",
                        "scope": "text",
                        "literal": True,
                    },
                )
            ).model_dump(by_alias=True)
            assert not response.get("isError"), response
            result = json.loads(
                next(c["text"] for c in response["content"] if c["type"] == "text")
            )
            assert [row["path"] for row in result["results"]] == ["sample.py"]

    # The SDK binds its default stderr at import time, which can retain another
    # test's capsys stream without a real file descriptor. Own a process log.
    with (tmp_path / "mcp-stderr.log").open("w") as errlog:
        asyncio.run(scenario(errlog))


@pytest.mark.parametrize(
    "content",
    [
        "bad JSON",
        "{}",
        '[{"insert": {}}]',
        '[{"insert":[{"id":"ken-mcp","name":"other"}]}]',
    ],
)
def test_invalid_or_conflicting_overlay_is_not_replaced(tmp_path, content):
    path = tmp_path / DEEPSEEK_OVERLAY
    path.parent.mkdir()
    path.write_text(content)
    with pytest.raises(ValueError):
        wire_deepseek(tmp_path, verbose=False)
    assert path.read_text() == content
