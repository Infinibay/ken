"""MCP/CLI parity, persistent memory, and source-backed responsibility evidence."""

import asyncio
import json
import sys

import pytest

from ken.cli import main
from ken.db import connect, init_schema
from ken.mcp import server
from ken.checks.service import check
from tests.test_checks import contract as contract, QUERY, GOOD, BAD
from tests.test_responsibility import project as project


@pytest.fixture
def tools_project(contract, monkeypatch):
    root, definition = contract
    (root / ".ken/meta.json").write_text("{}")
    with connect(root / ".ken/ken.db") as conn:
        init_schema(conn)
    monkeypatch.setattr(server, "_PROJECT_ROOT", root)
    return root, definition


def test_cli_accepts_complete_rule_objects_and_shares_mcp_contract(
    tools_project, capsys
):
    root, definition = tools_project
    assert main(["tools", "--path", str(root), "rule", "--action", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == server.ken_rule()
    other = definition | {"id": "other.return-id"}
    assert (
        main(
            [
                "tools",
                "--path",
                str(root),
                "rule",
                "--action",
                "create",
                "--definition",
                json.dumps(other),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "draft"
    result = server.ken_check(rules=[definition["id"]], full=True)
    assert (
        main(
            [
                "tools",
                "--path",
                str(root),
                "check",
                "--run-id",
                result["run_id"],
                "--full",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == result


def test_search_registered_rules_and_inline_compact_full(tools_project):
    root, definition = tools_project
    compact = server.ken_find(
        scope="structure", query_language="kql/2", query=QUERY, path="src"
    )
    full = server.ken_find(
        scope="structure", query_language="kql/2", query=QUERY, path="src", full=True
    )
    assert compact["rows"] == full["rows"]
    assert "analysis" not in compact and "analysis" in full
    found = server.ken_find(scope="structure", rules=[definition["id"]])
    assert found["results"][0]["result"]["rows"]
    check(root, rules=[definition["id"]])
    assert server.ken_related("src/store.py", "checks")["checks"][0]["status"] == "pass"


def test_receipt_memory_survives_restart_without_query_replay(
    tools_project, monkeypatch
):
    root, definition = tools_project
    result = server.ken_check(rules=[definition["id"]])
    monkeypatch.setattr(
        "ken.memory.get_embedder",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    saved = server.ken_remember(
        "storage-contract",
        "The selected wrapper returned the save result.",
        check_run=result["run_id"],
        anchor_file="src/store.py",
    )
    assert saved["ok"], saved
    monkeypatch.setattr(
        "ken.checks.execution.run",
        lambda *a, **kw: pytest.fail("recall must not run queries"),
    )
    recalled = server.ken_recall(topic="storage-contract")["finding"]
    assert recalled["validity"]["state"] == "unchanged"
    assert recalled["validity"]["checks"][0]["status"] == "pass"
    (root / "src/added.py").write_text("def another(): pass")
    recalled = server.ken_recall(topic="storage-contract", detail="summary")
    assert recalled["memories"][0]["validity"]["state"] == "stale"
    with pytest.raises(ValueError, match="rerun"):
        server.ken_remember("stale", "Old conclusion", check_run=result["run_id"])


def test_unknown_check_remains_unknown_in_memory(tools_project, monkeypatch):
    root, definition = tools_project
    (root / "src/unsupported.c").write_text("int x;")
    result = server.ken_check(rules=[definition["id"]])
    assert result["status"] == "unknown"
    monkeypatch.setattr(
        "ken.memory.get_embedder",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert server.ken_remember(
        "limited", "Inspection was incomplete", check_run=result["run_id"]
    )["ok"]
    finding = server.ken_recall(topic="limited")["finding"]
    assert finding["validity"]["checks"][0]["status"] == "unknown"


def test_who_observes_calls_and_retained_return_without_inventing_probability(project):
    root, _, add = project
    add("store.py", GOOD)
    plain = server.ken_who(
        "Save a user and return the identifier", verify=False, full=True
    )
    result = server.ken_who("Save a user and return the identifier", full=True)
    first = result["candidates"][0]
    assert first["symbol"] == "save_user"
    assert first["confidence"] == plain["candidates"][0]["confidence"]
    evidence = first["structure"]["evidence"]
    assert evidence["calls"]["sites"][0]["name"] == "save"
    assert evidence["returned_calls"]["sites"], evidence
    assert first["source"]["behavior_verified"] is False
    (root / "store.py").write_text(BAD)
    changed = server.ken_who("Save a user and return the identifier", full=True)
    assert not changed["candidates"][0]["structure"]["evidence"]["returned_calls"][
        "sites"
    ]


def test_real_stdio_publishes_and_runs_check_rule_find_related_and_memory(
    tools_project,
):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root, definition = tools_project

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ken", "mcp", str(root)],
            cwd=str(root),
            env={"HF_HUB_OFFLINE": "1"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=30) as session:
                await session.initialize()
                published = {
                    tool.name: tool for tool in (await session.list_tools()).tools
                }
                assert {"ken_rule", "ken_check", "ken_who"} <= published.keys()
                assert (
                    published["ken_check"].input_schema["properties"]["full"]["default"]
                    is False
                )

                async def call(name, args):
                    result = (await session.call_tool(name, args)).model_dump(
                        by_alias=True
                    )
                    assert not result.get("isError"), result
                    return json.loads(
                        next(
                            c["text"] for c in result["content"] if c["type"] == "text"
                        )
                    )

                validated = await call(
                    "ken_rule", {"action": "validate", "rule_id": definition["id"]}
                )
                assert validated["state"] == "validated"
                await call(
                    "ken_rule", {"action": "enable", "rule_id": definition["id"]}
                )
                before = await call("ken_check", {})
                assert before["status"] == "pass"
                saved = await call(
                    "ken_remember",
                    {
                        "topic": "checked-return",
                        "content": "The selected source contract passed.",
                        "check_run": before["run_id"],
                    },
                )
                assert saved["ok"]
                memory = await call(
                    "ken_recall", {"topic": "checked-return", "detail": "summary"}
                )
                assert memory["memories"][0]["validity"]["state"] == "unchanged"
                found = await call(
                    "ken_find", {"scope": "structure", "rules": [definition["id"]]}
                )
                assert found["results"][0]["result"]["rows"]
                impact = await call(
                    "ken_related", {"target": "src/store.py", "relation": "checks"}
                )
                assert impact["checks"][0]["status"] == "pass"
                (root / "src/store.py").write_text(BAD)
                after = await call("ken_check", {"compare": before["run_id"]})
                assert after["comparison"]["changes"][0]["change"] == "regression"
                assert "analysis" not in after["checks"][0]
                full = await call(
                    "ken_check", {"run_id": after["run_id"], "full": True}
                )
                assert full["checks"][0]["query"] == QUERY

    asyncio.run(scenario())
