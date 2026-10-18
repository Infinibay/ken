"""Resolved query text and all imported modules belong to one registry revision."""

import pytest

from ken.kql2.module_inputs import ModuleResolver
from ken.kql2.registry import ModuleRegistry


LIBRARY = '''language "kql/2"; module project.types;
pattern HasWrite(in TypeDecl $owner) {
  class $owner {method $method {name:"write";}}
}'''
MIDDLE = '''language "kql/2"; module project.conventions; import project.types;
pattern Writer(in TypeDecl $owner) {use project.types.HasWrite(owner:$owner);}'''
ENTRY = '''language "kql/2"; module project.search; import project.conventions;
query writers {class $owner {} use project.conventions.Writer(owner:$owner); select $owner.name;}'''


def test_resolves_saved_entry_and_transitive_imports(tmp_path):
    registry = ModuleRegistry(tmp_path)
    for source in (LIBRARY, MIDDLE, ENTRY):
        registry.save(source)
    with ModuleResolver(tmp_path) as resolver:
        resolved = resolver.resolve(saved_query="project.search", query_name="writers")
    assert resolved.source == ENTRY
    assert resolved.query_name == "writers"
    assert resolved.libraries == {"project.types": LIBRARY, "project.conventions": MIDDLE}
    assert set(resolved.revisions) == {"project.search", "project.types", "project.conventions"}


def test_inline_explicit_libraries_override_registered_modules(tmp_path):
    registry = ModuleRegistry(tmp_path)
    registry.save(LIBRARY)
    registry.save(MIDDLE)
    replacement = LIBRARY.replace('name:"write"', 'name:"close"')
    with ModuleResolver(tmp_path) as resolver:
        resolved = resolver.resolve(ENTRY, libraries={"project.types": replacement})
    assert resolved.libraries["project.types"] == replacement
    assert resolved.revisions.keys() == {"project.conventions"}


def test_live_resolver_sees_updates_without_mutating_prior_inputs(tmp_path):
    registry = ModuleRegistry(tmp_path)
    before = registry.save(LIBRARY)
    registry.save(MIDDLE)
    with ModuleResolver(tmp_path) as resolver:
        old = resolver.resolve(ENTRY)
        replacement = LIBRARY.replace('name:"write"', 'name:"close"')
        after = registry.save(replacement, expected_revision=before.revision)
        new = resolver.resolve(ENTRY)
    assert old.libraries["project.types"] == LIBRARY
    assert new.libraries["project.types"] == replacement
    assert old.revisions["project.types"] == before.revision
    assert new.revisions["project.types"] == after.revision


def test_cyclic_imports_keep_existing_language_semantics(tmp_path):
    registry = ModuleRegistry(tmp_path)
    original = registry.save(LIBRARY)
    registry.save(MIDDLE)
    registry.save(LIBRARY.replace("pattern HasWrite", "import project.conventions; pattern HasWrite"),
                  expected_revision=original.revision)
    with ModuleResolver(tmp_path) as resolver:
        resolved = resolver.resolve(ENTRY)
    assert set(resolved.libraries) == {"project.types", "project.conventions"}


def test_reader_detects_registry_created_after_resolver(tmp_path):
    with ModuleResolver(tmp_path) as resolver:
        with pytest.raises(ValueError, match="missing.*project.conventions"):
            resolver.resolve(ENTRY)
        registry = ModuleRegistry(tmp_path)
        registry.save(LIBRARY)
        registry.save(MIDDLE)
        assert resolver.resolve(ENTRY).libraries["project.types"] == LIBRARY


@pytest.mark.parametrize("source,saved", [(None,None),(ENTRY,"project.search")])
def test_exactly_one_entry_source_is_required(tmp_path, source, saved):
    with ModuleResolver(tmp_path) as resolver:
        with pytest.raises(ValueError, match="source|saved_query"):
            resolver.resolve(source, saved_query=saved)
    assert not (tmp_path / ".ken").exists()


def test_patterns_only_module_is_not_executable(tmp_path):
    ModuleRegistry(tmp_path).save(LIBRARY)
    with ModuleResolver(tmp_path) as resolver:
        with pytest.raises(ValueError, match="no executable query"):
            resolver.resolve(saved_query="project.types")


def test_resolved_inputs_are_immutable(tmp_path):
    registry = ModuleRegistry(tmp_path)
    registry.save(LIBRARY)
    registry.save(MIDDLE)
    with ModuleResolver(tmp_path) as resolver:
        resolved = resolver.resolve(ENTRY)
        with pytest.raises(TypeError):
            resolved.libraries["project.types"] = "changed"
        with pytest.raises(TypeError):
            resolved.revisions["project.types"] = "changed"


def test_resolver_detects_database_alias_retarget_inside_project(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    for root, source in ((one,LIBRARY),(two,LIBRARY.replace('name:"write"', 'name:"close"'))):
        registry = ModuleRegistry(root)
        registry.save(source)
        registry.save(MIDDLE)
    directory = tmp_path / ".ken"
    directory.mkdir()
    link = directory / "ken.db"
    link.symlink_to(one / ".ken/ken.db")
    with ModuleResolver(tmp_path) as resolver:
        before = resolver.resolve(ENTRY)
        link.unlink()
        link.symlink_to(two / ".ken/ken.db")
        after = resolver.resolve(ENTRY)
    assert 'name:"write"' in before.libraries["project.types"]
    assert 'name:"close"' in after.libraries["project.types"]


def _project(root):
    (root / "code.py").write_text('class Writer:\n def write(self): pass\nclass Closer:\n def close(self): pass\n')
    registry = ModuleRegistry(root)
    for source in (LIBRARY, MIDDLE, ENTRY):
        registry.save(source)
    return registry


@pytest.mark.parametrize("route", ["service", "session", "host"])
def test_execution_resolves_registry_and_tracks_updates_without_source_rebuild(tmp_path, route):
    from contextlib import nullcontext
    from ken.kql2.service import search
    from ken.kql2.session import QuerySession
    from ken.kql2.host import QueryHost

    registry = _project(tmp_path)
    owner = (QuerySession(tmp_path) if route == "session" else
             QueryHost(tmp_path, watch=False) if route == "host" else None)
    with owner if owner is not None else nullcontext():
        run = owner.search if owner is not None else lambda **kw: search(tmp_path, cache_mb=0, **kw)
        before = run(saved_query="project.search", query_name="writers")
        assert before["rows"] == [["Writer"]]
        original = registry.get("project.types")
        updated = registry.save(LIBRARY.replace('name:"write"', 'name:"close"'), expected_revision=original.revision)
        after = run(saved_query="project.search", query_name="writers")
        assert after["rows"] == [["Closer"]]
        assert after["analysis"]["registry_modules"]["project.types"] == updated.revision
        if owner is not None:
            assert after["analysis"]["snapshot"] == before["analysis"]["snapshot"]
            assert after["analysis"]["parsed_units"] == 0
            assert after["analysis"]["result_cache"] == "disabled"
        overridden = run(source=ENTRY, libraries={"project.types":LIBRARY})
        assert overridden["rows"] == [["Writer"]]
        assert "project.types" not in overridden["analysis"]["registry_modules"]


def test_inline_resolver_does_not_touch_registry_and_rejects_use_after_close(tmp_path, monkeypatch):
    import sqlite3
    def forbidden(*args, **kwargs):
        pytest.fail("inline source opened a registry database")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    resolver = ModuleResolver(tmp_path)
    assert resolver.resolve(LIBRARY).source == LIBRARY
    resolver.close()
    with pytest.raises(RuntimeError, match="closed"):
        resolver.resolve(LIBRARY)


def test_cli_and_mcp_save_inspect_execute_and_delete(tmp_path, monkeypatch, capsys):
    from ken.cli import main
    from ken.mcp import server
    from ken.kql2 import automatic

    (tmp_path / "code.py").write_text('class Writer:\n def write(self): pass\n')
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("management or explain started prepared query service")
    monkeypatch.setattr(automatic, "_ensure", forbidden)
    query_file = tmp_path / "types.kql"
    query_file.write_text(LIBRARY)
    assert main(["kql2", str(query_file), "--root", str(tmp_path), "--save"]) == 0
    import json
    saved = json.loads(capsys.readouterr().out)
    assert saved["module"] == "project.types"
    assert server.ken_query(action="list")["modules"][0]["revision"] == saved["revision"]
    assert server.ken_query(action="show", module="project.types")["source"] == LIBRARY
    server.ken_query(action="save", source=MIDDLE)
    server.ken_query(action="save", source=ENTRY)
    result = server.ken_find(scope="structure", query_language="kql/2", saved_query="project.search",
                             query_name="writers", cache_mb=0)
    assert result["rows"] == [["Writer"]]
    assert set(result["registry_modules"]) == {"project.types", "project.conventions", "project.search"}
    assert main(["kql2", "--saved", "project.search", "--root", str(tmp_path), "--query", "writers", "--explain", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["query"] == "writers"
    assert main(["kql2", "--saved", "project.search", "--root", str(tmp_path), "--cache-mb", "0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [["Writer"]]
    with pytest.raises(ValueError, match="source|saved_query"):
        server.ken_find(query=ENTRY, saved_query="project.search", scope="structure", query_language="kql/2", cache_mb=0)
    with pytest.raises(ValueError, match="kql/2"):
        server.ken_find(saved_query="project.search", scope="structure")
    server.ken_query(action="delete", module="project.search")
    with pytest.raises(ValueError, match="not found"):
        server.ken_query(action="show", module="project.search")


def test_source_contract_pins_registered_imports_before_validation(tmp_path):
    from ken.checks.rules import manage
    registry = _project(tmp_path)
    definition = {"id":"test.writers", "description":"writer witness", "query":ENTRY,
                  "expectation":"some_match", "examples":[
                      {"name":"writer", "files":{"a.py":"class A:\n def write(self): pass\n"}, "expect":"pass"},
                      {"name":"other", "files":{"a.py":"class A: pass\n"}, "expect":"fail"}]}
    created = manage(tmp_path, "create", definition=definition, full=True)
    assert created["definition"]["libraries"]["project.types"] == LIBRARY
    old = registry.get("project.types")
    registry.save(LIBRARY.replace('name:"write"', 'name:"close"'), expected_revision=old.revision)
    validated = manage(tmp_path, "validate", rule_id="test.writers")
    assert validated["state"] == "validated", validated
    assert validated["revision"] == created["revision"]


def test_cli_library_files_do_not_replace_entry_source(tmp_path, capsys):
    from ken.cli import main
    import json
    (tmp_path / "code.py").write_text('class Writer:\n def write(self): pass\n')
    paths = []
    for name, source in (("entry",ENTRY), ("types",LIBRARY), ("middle",MIDDLE)):
        path = tmp_path / (name + ".kql")
        path.write_text(source)
        paths.append(path)
    command = ["kql2", str(paths[0]), "--root", str(tmp_path), "--library", str(paths[1]), "--library", str(paths[2]), "--json"]
    assert main(command + ["--explain"]) == 0
    assert json.loads(capsys.readouterr().out)["query"] == "writers"
    assert main(command + ["--cache-mb", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [["Writer"]]


def test_first_registry_creation_does_not_refresh_source_index(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2 import session as sessions
    (tmp_path / "a.py").write_text('class Writer:\n def write(self): pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        before = host.search('language "kql/2"; module plain; query q {select 1;}')
        def forbidden(*args, **kwargs):
            pytest.fail("registry metadata changes refreshed the source index")
        monkeypatch.setattr(sessions, "search", forbidden)
        for source in (LIBRARY, MIDDLE, ENTRY):
            ModuleRegistry(tmp_path).save(source)
        after = host.search(saved_query="project.search")
        assert after["rows"] == [["Writer"]]
        assert after["analysis"]["snapshot"] == before["analysis"]["snapshot"]
        assert after["analysis"]["preparation_ms"] == 0


@pytest.mark.parametrize("backend", ["indexed", "exploration"])
def test_named_query_survives_supervised_request_boundary(tmp_path, backend):
    from ken.kql2.service import search
    registry = _project(tmp_path)
    module, query, expected = "project.search", "writers", [["Writer"]]
    if backend == "exploration":
        registry.save('language "kql/2"; module project.syntax; query value_query {select 7;}')
        module, query, expected = "project.syntax", "value_query", [[7]]
    result = search(tmp_path, saved_query=module, query_name=query, cache_mb=0,
                    timeout_ms=10000, backend=backend)
    assert result["complete"], result
    assert result["rows"] == expected
    assert module in result["analysis"]["registry_modules"]


def test_host_uses_one_registry_snapshot_through_preparation(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2.session import QuerySession
    registry = _project(tmp_path)
    before = registry.get("project.types")
    original = QuerySession.prepare_query
    changed = False
    def update_between_prepare_and_execution(self, *args, **kwargs):
        nonlocal changed
        result = original(self, *args, **kwargs)
        if not changed:
            changed = True
            registry.save(LIBRARY.replace('name:"write"','name:"close"'), expected_revision=before.revision)
        return result
    monkeypatch.setattr(QuerySession, "prepare_query", update_between_prepare_and_execution)
    with QueryHost(tmp_path, watch=False) as host:
        first = host.search(saved_query="project.search")
        second = host.search(saved_query="project.search")
    assert first["rows"] == [["Writer"]]
    assert first["analysis"]["registry_modules"]["project.types"] == before.revision
    assert second["rows"] == [["Closer"]]
    assert second["analysis"]["registry_modules"]["project.types"] != before.revision


def test_real_stdio_registry_and_new_cli_processes_share_prepared_session(tmp_path):
    import asyncio
    import json
    import os
    import subprocess
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from ken.kql2 import automatic

    (tmp_path / "a.py").write_text('class Writer:\n def write(self): pass\nclass Closer:\n def close(self): pass\n')
    (tmp_path / ".ken").mkdir()
    (tmp_path / ".ken/meta.json").write_text("{}\n")
    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "ken", "mcp", str(tmp_path)],
            cwd=str(tmp_path), env=os.environ.copy(),
        )
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                published = {tool.name:tool for tool in (await client.list_tools()).tools}
                assert "ken_query" in published
                assert "saved_query" in published["ken_find"].input_schema["properties"]
                async def call(name, args):
                    response = await client.call_tool(name, {**args, "output_format": "json"})
                    assert not response.is_error, response
                    return json.loads(response.content[0].text)
                for source in (LIBRARY, MIDDLE, ENTRY):
                    await call("ken_query", {"action":"save", "source":source})
                before = await call("ken_find", {"scope":"structure", "query_language":"kql/2",
                                    "saved_query":"project.search", "full":True})
                assert before["rows"] == [["Writer"]]
                old = await call("ken_query", {"action":"show", "module":"project.types"})
                await call("ken_query", {"action":"save", "source":LIBRARY.replace('name:"write"','name:"close"'),
                                          "expected_revision":old["revision"]})
                command = [sys.executable,"-m","ken.kql2","--root",str(tmp_path),"--saved","project.search","--query","writers","--json"]
                child = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, timeout=30)
                assert child.returncode == 0, child.stderr
                after = json.loads(child.stdout)
                assert after["rows"] == [["Closer"]]
                assert after["analysis"]["session_pid"] == before["analysis"]["session_pid"]
                assert after["analysis"]["snapshot"] == before["analysis"]["snapshot"]
                assert after["analysis"]["preparation_ms"] == 0
    try:
        with (tmp_path / "mcp-stderr.log").open("w") as errlog:
            asyncio.run(scenario())
    finally:
        automatic.shutdown(tmp_path)


def test_cli_explanation_captures_packaged_imports_once(tmp_path, monkeypatch, capsys):
    from ken.cli import main
    from ken.kql2 import catalog
    source = 'language "kql/2"; module example; import ken.catalog.builder; query builders {use ken.catalog.builder.detect(builder:$builder); select $builder;}'
    query_file = tmp_path / "builder.kql"
    query_file.write_text(source)
    original = catalog.sources
    calls = []
    def once():
        calls.append(True)
        assert len(calls) == 1, "catalog captured twice"
        return original()
    monkeypatch.setattr(catalog, "sources", once)
    assert main(["kql2", str(query_file), "--root", str(tmp_path), "--explain", "--json"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["query"] == "builders"
    assert len(calls) == 1
