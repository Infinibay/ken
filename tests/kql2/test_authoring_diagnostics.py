"""Real review mistakes must be explainable without silently changing rows."""

import json

import pytest

from ken.cli import main
from ken.kql2.explanation import explain
from ken.kql2.service import search

FIXTURE = """def reraises():
    try:
        work()
    except ValueError:
        raise

def ignores():
    try:
        work()
    except ValueError:
        pass

def retries(items):
    for item in items:
        try:
            work(item)
        except ValueError:
            continue
"""


def query(body):
    return 'language "kql/2"; module review; query example { ' + body + " }"


def codes(result):
    return {d["code"] for d in result.get("diagnostics", [])}


@pytest.mark.parametrize("backend", ["exploration", "indexed"])
def test_disconnected_witness_does_not_mean_every_handler_continues(tmp_path, backend):
    (tmp_path / "example.py").write_text(FIXTURE)
    source = query(
        'node $handler {kind:"catch";} node $witness {kind:"continue";} select $handler.line;'
    )
    disconnected = search(tmp_path, source, backend=backend, cache_mb=0)
    assert len(disconnected["rows"]) == 3
    assert "disconnected_captures" in codes(disconnected)
    joined = search(
        tmp_path,
        source.replace("select ", "where contains($handler,$witness); select "),
        backend=backend,
        cache_mb=0,
    )
    assert joined["rows"] == [[17]]
    assert not joined.get("diagnostics")


@pytest.mark.parametrize("backend", ["exploration", "indexed"])
def test_global_and_correlated_negation_remain_distinct(tmp_path, backend):
    (tmp_path / "example.py").write_text(FIXTURE)
    source = query(
        'node $handler {kind:"catch";} not exists {node $raised {kind:"throw";} } select $handler.line;'
    )
    global_result = search(tmp_path, source, backend=backend, cache_mb=0)
    assert global_result["rows"] == []
    assert "uncorrelated_exists" in codes(global_result)
    local = source.replace(
        'node $raised {kind:"throw";} ',
        'node $raised {kind:"throw";} where contains($handler,$raised); ',
    )
    result = search(tmp_path, local, backend=backend, cache_mb=0)
    assert result["rows"] == [[10], [17]]
    assert not result.get("diagnostics")


def test_intentional_independent_domains_warn_but_execute_and_cache(tmp_path):
    (tmp_path / "example.py").write_text("class A: pass\nclass B: pass")
    source = query("class $a {} class $b {} select $a.name,$b.name;")
    first = search(tmp_path, source, cache_mb=20)
    second = search(tmp_path, source, cache_mb=20)
    assert len(first["rows"]) == 4
    assert first["rows"] == second["rows"]
    assert first["diagnostics"] == second["diagnostics"]
    assert second["analysis"]["result_cache"] == "disk_hit"


@pytest.mark.parametrize(
    "property,expected",
    [("parent:$owner", "contains_direct"), ('value:"True"', 'text: "True"')],
)
def test_invalid_properties_have_actionable_replacements(tmp_path, property, expected):
    source = query("node $owner {} node $child {" + property + ";} select $owner;")
    with pytest.raises(ValueError, match=expected):
        search(tmp_path, source, backend="exploration")
    assert not (tmp_path / ".ken").exists()


@pytest.mark.parametrize(
    "constraint,code",
    [
        ('kind:"except";', "unknown_syntax_kind"),
        ('kind:"identifier"; name:"None";', "syntax_spelling_mismatch"),
        ('kind:"identifier"; name:"*";', "syntax_spelling_mismatch"),
    ],
)
def test_empty_result_traps_are_visible_before_execution(constraint, code):
    assert code in codes(
        explain(query("node $n {" + constraint + "} select $n;"), backend="exploration")
    )


def test_capabilities_and_explain_do_not_acquire_a_project(tmp_path, capsys):
    source = tmp_path / "example.kql"
    source.write_text(
        query('node $h {kind:"catch";} node $c {kind:"continue";} select $h;')
    )
    assert (
        main(
            [
                "kql2",
                str(source),
                "--root",
                str(tmp_path / "missing"),
                "--explain",
                "--backend",
                "exploration",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["executed"] is False and "disconnected_captures" in codes(result)
    assert main(["kql2", "--capabilities"]) == 0
    matrix = json.loads(capsys.readouterr().out)["backends"]
    assert matrix["indexed"]["body"] and not matrix["exploration"]["body"]
    assert matrix["exploration"]["properties"]["text"] == "String"
    assert not (tmp_path / ".ken").exists()


def test_body_is_supported_in_indexed_and_rejected_with_routing_help():
    source = query(
        'callable $f {body {let $value = call $site {name:"save";}; return $value;}} select $f;'
    )
    assert explain(source, backend="indexed")["validated"]
    with pytest.raises(ValueError, match="--backend indexed"):
        explain(source, backend="exploration")


def test_body_bound_target_is_a_relationship_not_a_cartesian_product():
    source = query(
        'callable $target {name:"save";} callable $owner {body {let $v = call $target {}; return $v;}} select $owner;'
    )
    assert not explain(source)["diagnostics"]


def test_misplaced_return_explains_its_enclosing_syntax():
    source = query("callable $owner {return $value;} select $owner;")
    with pytest.raises(ValueError, match="callable BODY block"):
        explain(source)


def test_mcp_compact_and_full_preserve_authoring_diagnostics(tmp_path, monkeypatch):
    from ken.mcp import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "example.py").write_text(FIXTURE)
    source = query('node $h {kind:"catch";} node $c {kind:"continue";} select $h.line;')
    for full in (False, True):
        result = server.ken_find(
            query=source,
            scope="structure",
            query_language="kql/2",
            cache_mb=0,
            full=full,
        )
        assert "disconnected_captures" in codes(result)
        assert len(result["rows"]) == 3


def test_boolean_independent_tests_do_not_create_a_join():
    source = query(
        'node $a {} node $b {} where $a.kind == "catch" and $b.kind == "continue"; select $a;'
    )
    assert "disconnected_captures" in codes(explain(source, backend="exploration"))


def test_nested_absence_and_bound_identity_are_correlated():
    source = query('class $c {not exists {method $m {name:"close";}}} select $c;')
    assert not explain(source)["diagnostics"]
    source = query("node $a {} node $b {} where $a == $b; select $a;")
    assert not explain(source, backend="exploration")["diagnostics"]


def test_timeout_preserves_compile_diagnostics(tmp_path, monkeypatch):
    import time

    from ken.kql2.request import _failure

    source = query("node $h {} node $c {} select $h;")
    diagnostics = explain(source)["diagnostics"]
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"phase": "persist", "query": "example", "diagnostics": diagnostics})
    )
    result = _failure(
        progress, {"backend": "indexed", "timeout_ms": 1}, time.monotonic()
    )
    assert not result["complete"] and result["diagnostics"] == diagnostics
