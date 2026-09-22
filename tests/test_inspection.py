"""Public source inspection: imports, identities, consumers and honest boundaries."""

import json

import pytest

from ken.inspection.graph import Program
from ken.inspection.service import inspect
from ken.mcp import server
from ken.cli import main


@pytest.fixture
def project(tmp_path):
    files = {
        "storage.py": "def save():\n return 7\n",
        "api.py": "from storage import save\ndef wrapper():\n return save()\n",
        "tests/test_api.py": "from api import wrapper\ndef test_value():\n value=wrapper()\n return value\n",
        "unrelated.py": "def unrelated():\n return save()\n",
        "other.py": "def save():\n return 99\n",
    }
    for name, source in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source)
    return tmp_path


def test_result_propagates_across_explicit_imports_to_tests(project):
    result = inspect(project, "storage.py::save", depth=3)
    assert [c["caller"]["name"] for c in result["consumers"]] == [
        "wrapper",
        "test_value",
    ]
    assert result["consumers"][0]["result_uses"][0]["kind"] == "return"
    assert result["tests"][0]["caller"]["path"] == "tests/test_api.py"
    assert "unrelated.py" not in result["acquisition"]["paths"]
    assert "other.py" not in result["acquisition"]["paths"]


@pytest.mark.parametrize("target", ["api.py", "api.py::wrapper"])
def test_role_nodes_are_declarations_and_keep_call_sites_separate(project, target):
    result = inspect(project, target, relation="roles")
    assert {n["symbol"] for n in result["nodes"]} == {"wrapper", "save", "test_value"}
    assert all(n["kind"] == "CALLABLE" for n in result["nodes"])
    assert result["calls"]
    assert all(c["call"]["kind"] == "CALL" for c in result["calls"])


def test_only_importers_of_the_requested_binding_are_acquired(project):
    with (project / "storage.py").open("a") as source:
        source.write("\ndef different():\n return 9\n")
    (project / "named_other.py").write_text(
        "from storage import different\ndef run():\n return different()\n"
    )
    (project / "namespace_other.py").write_text(
        "import storage as store\ndef run():\n return store.different()\n"
    )
    result = inspect(project, "storage.py::save", depth=3, full=True)
    assert [c["caller"]["name"] for c in result["consumers"]] == [
        "wrapper",
        "test_value",
    ]
    assert set(result["acquisition"]["paths"]) == {
        "storage.py",
        "api.py",
        "tests/test_api.py",
    }
    assert len(result["observations"]["definitions"]["rows"]) == 1


def test_unrelated_call_results_cannot_exhaust_the_requested_usage_query(project):
    with (project / "storage.py").open("a") as source:
        for index in range(100):
            source.write(
                f"\ndef irrelevant_{index}():\n value=irrelevant_{index}()\n return value\n"
            )
    result = inspect(project, "storage.py::save", depth=3, full=True)
    assert [c["caller"]["name"] for c in result["consumers"]] == [
        "wrapper",
        "test_value",
    ]
    assert result["coverage"]["usages"]["complete"]
    assert len(result["observations"]["usages"]["rows"]) < 10


def test_a_transformation_stops_import_acquisition_as_well_as_propagation(project):
    (project / "api.py").write_text(
        "from storage import save\ndef wrapper():\n return save()+1\n"
    )
    result = inspect(project, "storage.py::save", depth=3)
    assert result["consumers"] and not result["tests"]
    assert "tests/test_api.py" not in result["acquisition"]["paths"]


def test_coherent_partial_observations_survive_an_interrupted_frontier(
    project, monkeypatch
):
    from ken.inspection.exploration import Explorer
    from ken.inspection.graph import Program

    request = {
        "root": str(project),
        "path": ".",
        "timeout_ms": 10000,
        "max_rows": 100,
        "focus": {"targets": ["storage.py::save"], "relation": "impact", "depth": 3},
    }
    explorer = Explorer(request)
    monkeypatch.setattr(
        explorer,
        "step",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("test interruption")),
    )
    program = Program.from_batch(".", explorer.run())
    assert program.select("storage.py::save")
    assert not program.coverage()["calls"]["complete"]


def test_source_change_discards_a_graph_assembled_from_different_revisions(
    project, monkeypatch
):
    from ken.inspection.exploration import Explorer
    from ken.inspection.graph import Program

    request = {
        "root": str(project),
        "path": ".",
        "timeout_ms": 10000,
        "max_rows": 100,
        "focus": {"targets": ["storage.py::save"], "relation": "impact", "depth": 3},
    }
    explorer = Explorer(request)
    original = explorer.step

    def step(*args, **kwargs):
        original(*args, **kwargs)
        (project / "storage.py").write_text("def save():\n return 88\n")

    monkeypatch.setattr(explorer, "step", step)
    program = Program.from_batch(".", explorer.run())
    assert not program.nodes and not program.calls and not program.uses
    assert program.coverage()["calls"]["reason"] == "source_changed_during_inspection"


def test_missing_import_never_links_same_named_function(project):
    (project / "api.py").write_text("def wrapper():\n return save()\n")
    result = inspect(project, "storage.py::save", depth=3)
    assert not result["consumers"]
    graph = Program.inspect(project)
    call = next(c for c in graph.calls if c["site"]["path"] == "api.py")
    assert call["resolution"] == "unresolved"
    assert not call["targets"]


@pytest.mark.parametrize(
    "source",
    [
        "import storage as s\ndef wrapper():\n return s.save()\n",
        "from storage import save as persist\ndef wrapper():\n return persist()\n",
    ],
)
def test_import_alias_is_resolved_by_identity(project, source):
    (project / "api.py").write_text(source)
    result = inspect(project, "storage.py::save")
    assert result["consumers"][0]["caller"]["name"] == "wrapper"


@pytest.mark.parametrize(
    "imports,call",
    [
        (
            "try:\n import storage as backend\nexcept ImportError:\n import external_store as backend\n",
            "backend.save()",
        ),
        (
            "try:\n from storage import save as persist\nexcept ImportError:\n from external_store import save as persist\n",
            "persist()",
        ),
    ],
)
def test_missing_import_alternative_never_becomes_a_certain_call(
    project, imports, call
):
    (project / "api.py").write_text(imports + f"def wrapper():\n return {call}\n")
    result = inspect(project, "storage.py::save", depth=3)
    assert result["consumers"]
    assert all(c["resolution"] == "ambiguous" for c in result["consumers"])
    assert not result["tests"]  # An uncertain return cannot propagate as identity.


def test_imported_package_submodule_is_a_namespace_not_a_same_named_method(tmp_path):
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/storage.py").write_text("def save():\n return 1\n")
    (tmp_path / "app.py").write_text(
        "from pkg import storage as backend\ndef wrapper():\n return backend.save()\n"
    )
    result = inspect(tmp_path, "src/pkg/storage.py::save")
    assert result["consumers"][0]["caller"]["name"] == "wrapper"


def test_conditional_alias_targets_are_ambiguous(project):
    (project / "api.py").write_text(
        "if flag:\n import storage as backend\nelse:\n import other as backend\ndef wrapper():\n return backend.save()\n"
    )
    graph = Program.inspect(project)
    call = next(c for c in graph.calls if c["site"]["path"] == "api.py")
    assert call["resolution"] == "ambiguous"
    assert len(call["targets"]) == 2


@pytest.mark.parametrize(
    "source",
    [
        "import storage as s\ndef wrapper(s):\n return s.save()\n",
        "import storage as s\ndef wrapper():\n s=object()\n return s.save()\n",
        "from storage import save\ndef wrapper(save):\n return save()\n",
    ],
)
def test_shadowed_import_does_not_establish_dependency(project, source):
    (project / "api.py").write_text(source)
    result = inspect(project, "storage.py::save")
    assert not result["consumers"]


def test_distinct_occurrences_do_not_share_return_evidence(project):
    (project / "api.py").write_text(
        "from storage import save\ndef wrapper():\n save()\n return save()\n"
    )
    result = inspect(project, "storage.py::save")
    calls = [c for c in result["consumers"] if c["caller"]["path"] == "api.py"]
    assert len(calls) == 2
    assert not calls[0]["result_uses"]
    assert calls[1]["result_uses"][0]["kind"] == "return"
    assert calls[0]["usage_status"] == "unknown"


def test_imported_call_in_container_is_not_shadowed_by_its_own_reference(project):
    (project / "api.py").write_text(
        "from storage import save\ndef wrapper():\n return {'value': save()}\n"
    )
    result = inspect(project, "storage.py::save", depth=3)
    assert [c["caller"]["name"] for c in result["consumers"]] == ["wrapper"]
    assert result["consumers"][0]["resolution"] == "resolved"
    assert not result["tests"]  # Returning a container does not return the same value.


def test_transform_does_not_propagate_return_identity(project):
    (project / "api.py").write_text(
        "from storage import save\ndef wrapper():\n value=save()\n return value+1\n"
    )
    result = inspect(project, "storage.py::save", depth=3)
    assert [c["caller"]["name"] for c in result["consumers"]] == ["wrapper"]
    assert not result["tests"]


def test_roles_are_explained_hypotheses_with_canonical_locations(project):
    result = inspect(project, "api.py::wrapper", relation="roles", depth=3)
    nodes = {n["name"]: n for n in result["nodes"]}
    assert nodes["save"]["path"] == "storage.py"
    assert nodes["save"]["line"] == 1
    assert any(r["role"] == "executor_candidate" for r in nodes["save"]["roles"])
    assert any(r["role"] == "delegates" for r in nodes["wrapper"]["roles"])
    assert all(n["inference"] == "structural_hypothesis" for n in nodes.values())


def test_timeout_and_outside_scope_do_not_report_safe(project):
    result = inspect(project, "storage.py::save", timeout_ms=1)
    assert result["status"] == "unknown"
    assert not result["consumers"]
    assert any(not v.get("complete") for v in result["coverage"].values())
    result = inspect(project, "storage.py::save", path="other.py")
    assert result["status"] == "unknown"


def test_qualified_method_retains_its_class_identity(project):
    (project / "storage.py").write_text("class Store:\n def save(self):\n  return 7\n")
    result = inspect(project, "storage.py::Store.save", relation="roles")
    assert result["status"] == "observed"
    assert result["nodes"][0]["symbol"] == "Store.save"


def test_target_paths_are_normalized_and_confined(project):
    relative = inspect(project, "storage.py::save")
    absolute = inspect(project, f"{project / 'storage.py'}::save")
    assert absolute["consumers"] == relative["consumers"]
    with pytest.raises(ValueError):
        inspect(project, "../outside.py::save")
    (project / "escape.py").symlink_to(project.parent / "outside.py")
    with pytest.raises(ValueError):
        inspect(project, "escape.py::save")


def test_src_layout_and_relative_imports(tmp_path):
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/storage.py").write_text("def save():\n return 1\n")
    (tmp_path / "src/pkg/api.py").write_text(
        "from .storage import save\ndef wrapper():\n return save()\n"
    )
    (tmp_path / "app.py").write_text(
        "from pkg.api import wrapper\ndef main():\n return wrapper()\n"
    )
    result = inspect(tmp_path, "src/pkg/storage.py::save", depth=3)
    assert [c["caller"]["name"] for c in result["consumers"]] == ["wrapper", "main"]


def test_mcp_cli_share_compact_and_full_contract(project, monkeypatch, capsys):
    (project / ".ken").mkdir(exist_ok=True)
    (project / ".ken/meta.json").write_text("{}")
    monkeypatch.setattr(server, "_PROJECT_ROOT", project)
    compact = server.ken_related("storage.py::save", "impact", depth=3)
    assert compact["consumers"]
    assert "observations" not in compact
    assert (
        main(
            [
                "tools",
                "--path",
                str(project),
                "related",
                "storage.py::save",
                "impact",
                "--depth",
                "3",
                "--full",
            ]
        )
        == 0
    )
    full = json.loads(capsys.readouterr().out)
    assert compact["consumers"] == full["consumers"]
    assert full["observations"]["usages"]["rows"]


def test_cyclic_imports_terminate_and_unrelated_sources_remain_excluded(project):
    (project / "storage.py").write_text(
        "from api import wrapper\ndef save():\n return 7\n"
    )
    result = inspect(project, "storage.py::save")
    assert result["consumers"]
    assert "unrelated.py" not in result["acquisition"]["paths"]


def test_shared_dependency_does_not_expand_to_its_unrelated_importers(project):
    from ken.checks.snapshot import capture
    from ken.inspection.imports import select

    (project / "common.py").write_text("def helper():\n return 1\n")
    (project / "storage.py").write_text(
        "from common import helper\ndef save():\n return helper()\n"
    )
    (project / "unrelated.py").write_text(
        "from common import helper\ndef other():\n return helper()\n"
    )
    selected = select(project, capture(project, "."), ["storage.py"], incoming=True)
    assert {"storage.py", "common.py", "api.py", "tests/test_api.py"} <= set(
        selected["paths"]
    )
    assert "unrelated.py" not in selected["paths"]


def test_import_dependency_change_selects_rule_and_invalidates_memory_inputs(project):
    from ken.checks.rules import manage
    from ken.checks.service import check
    from ken.checks.integration import freshness

    query = 'language "kql/2"; module demo; query q { callable $f {name:"wrapper";} select $f; }'
    definition = {
        "id": "api.wrapper",
        "path": "api.py",
        "query": query,
        "description": "API declares a wrapper",
        "expectation": "some_match",
    }
    manage(project, "create", definition=definition)
    before = check(project, rules=[definition["id"]], full=True)
    assert before["status"] == "pass"
    (project / "storage.py").write_text("def save():\n return 2\n")
    assert freshness(project, before, seconds=2)["state"] == "stale"
    after = check(project, rules=[definition["id"]], touched=["storage.py"], full=True)
    assert after["checks"]
    assert after["selection_evidence"][definition["id"]]["basis"] == "import_dependency"
    by_path = check(project, rules=[definition["id"]], path="storage.py", full=True)
    assert by_path["checks"]
    assert (
        by_path["selection_evidence"][definition["id"]]["basis"] == "import_dependency"
    )
    from ken.checks.integration import related

    assert related(project, "storage.py")["rules"][0]["id"] == definition["id"]


def test_new_import_target_invalidates_previously_unresolved_dependency(project):
    from ken.inspection.imports import dependencies
    from ken.checks.snapshot import capture

    (project / "api.py").write_text(
        "from optional_store import save\ndef wrapper():\n return save()\n"
    )
    before = dependencies(project, capture(project, "api.py"))
    (project / "optional_store.py").write_text("def save():\n return 1\n")
    after = dependencies(project, capture(project, "api.py"))
    assert before != after


def test_contextual_availability_requires_an_explicit_access_spelling(project):
    (project / "consumer.py").write_text("import storage as backend\n")
    result = inspect(
        project, "storage.py::save", relation="available", from_path="consumer.py"
    )
    assert result["candidates"][0]["expression"] == "backend.save"
    assert result["candidates"][0]["obligations"]
    (project / "consumer.py").write_text("if configured:\n import storage as backend\n")
    result = inspect(
        project, "storage.py::save", relation="available", from_path="consumer.py"
    )
    assert result["status"] == "unknown" and not result["candidates"]


def test_granular_freshness_reports_which_rule_inputs_changed(project):
    from ken.checks.rules import manage
    from ken.checks.service import check
    from ken.checks.integration import freshness

    for name in ("storage", "other"):
        manage(
            project,
            "create",
            definition={
                "id": name,
                "description": name,
                "path": name + ".py",
                "expectation": "some_match",
                "query": 'language "kql/2"; module demo; query q { callable $f {} select $f; }',
            },
        )
    receipt = check(project, rules=["storage", "other"], full=True)
    (project / "storage.py").write_text("def save():\n return 11\n")
    validity = freshness(project, receipt, seconds=2)
    states = {c["rule"]: c for c in validity["checks"]}
    assert states["storage"]["validity"] == "stale"
    assert states["storage"]["changed_files"] == ["storage.py"]
    assert states["other"]["validity"] == "unchanged"


def test_explicit_source_inventory_is_reported_and_confined(project):
    from ken.kql2.service import search

    query = 'language "kql/2"; module demo; query q { callable $f {} select $f; }'
    result = search(project, query, source_paths=["storage.py"])
    assert result["source_scope"] == {"kind": "explicit_files", "paths": ["storage.py"]}
    assert len(result["rows"]) == 1
    with pytest.raises(ValueError, match="inside the analysis scope"):
        search(project, query, path="storage.py", source_paths=["other.py"])


def test_live_mcp_publishes_and_executes_inspection_modes(project):
    import asyncio
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from ken.db import connect, init_schema

    (project / ".ken").mkdir(exist_ok=True)
    (project / ".ken/meta.json").write_text("{}")
    with connect(project / ".ken/ken.db") as conn:
        init_schema(conn)

    async def scenario():
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "ken", "mcp", str(project)]
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                related = next(t for t in tools.tools if t.name == "ken_related")
                assert {"roles", "impact", "available"} <= set(
                    related.input_schema["properties"]["relation"]["enum"]
                )
                recall = next(t for t in tools.tools if t.name == "ken_recall")
                assert "answer" in recall.input_schema["properties"]["detail"]["enum"]
                remembered = await session.call_tool(
                    "ken_recall", {"topic": "missing", "detail": "answer"}
                )
                assert not remembered.is_error, remembered
                value = json.loads(remembered.content[0].text)
                assert value["detail"] == "answer" and value["memories"] == []
                for relation, extra in (
                    ("roles", {}),
                    ("impact", {}),
                    ("available", {"from_path": "api.py"}),
                ):
                    result = await session.call_tool(
                        "ken_related",
                        {"target": "storage.py::save", "relation": relation, **extra},
                    )
                    assert not result.is_error, result
                    value = json.loads(result.content[0].text)
                    assert value["status"] in {"observed", "candidates"}

    asyncio.run(scenario())


def test_ci_distinguishes_no_rules_from_a_success(project):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/check_contracts_ci.py"
    process = subprocess.run(
        [sys.executable, str(script), "--root", str(project)],
        text=True,
        capture_output=True,
    )
    assert process.returncode == 3
    assert json.loads(process.stdout)["status"] == "not_applicable"


def test_resource_review_frontier_follows_identity_without_claiming_release(project):
    (project / 'api.py').write_text('''from storage import save
def wrapper():
    value = save()
    alias = value
    value = object()
    value.close()
    alias.close()
    accept(alias)
    return alias
''')
    result = inspect(project, 'storage.py::save', depth=1)
    flow = result['consumers'][0]['result_flow']
    assert flow['ownership'] == 'unproven' and flow['inventory'] == 'open'
    boundaries = flow['boundaries']
    cleanup = [item for item in boundaries if item['status'] == 'cleanup_candidate']
    assert len(cleanup) == 1 and cleanup[0]['line'] == 7
    assert cleanup[0]['consumer']['name'] == 'close'
    argument = next(item for item in boundaries if item['status'] == 'argument_boundary')
    assert argument['consumer']['name'] == 'accept' and argument['position'] == 0
    returned = next(item for item in boundaries if item['status'] == 'returned_identity')
    assert not returned['followed'] and returned['stop_reason'] == 'depth_limit'


def test_transformation_frontier_says_why_identity_stops(project):
    (project / 'api.py').write_text('from storage import save\ndef wrapper():\n return save()+1\n')
    result = inspect(project, 'storage.py::save', depth=3)
    flow = result['consumers'][0]['result_flow']
    assert any(item['status'] == 'transformed_value' for item in flow['boundaries'])
    assert not result['tests']
