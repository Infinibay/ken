from __future__ import annotations

import json

import pytest

from ken.cli import main
from ken.mcp import server
from .gof_sources import PYTHON


def test_cli_pattern_scan_and_directory_summary(tmp_path, capsys):
    (tmp_path / "builder.py").write_text(PYTHON["builder"])
    # The directory rollup belongs to the verbatim result; the default surface is
    # the compact summary (see test_compact_report.py).
    assert main(["structural", "patterns", "--path", str(tmp_path), "--pattern", "builder",
                 "--cache-mb", "0", "--full"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["findings"] and result["directories"]


def test_cli_reads_query_file(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def search(user: str): return user")
    query = tmp_path / "query.kenq"
    query.write_text('method(name: /^search$/) as $m { has_parameter(type: str) as $p; }')
    assert main(["structural", "search", "--path", str(tmp_path), "--query-file", str(query), "--cache-mb", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["matches"]


def test_cli_catalog_documents_every_rule(capsys):
    assert main(["structural", "catalog"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["patterns"]) == 23
    assert len(result["bugs"]) == 8


def test_cli_ir_includes_ordered_operations_and_graph(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def generator(): yield 1")
    assert main(["structural", "ir", "--path", str(tmp_path), "--symbol", "generator", "--cache-mb", "0"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ir"]["operations"] and result["ir"]["facts"]


@pytest.mark.parametrize("scope,query,key", [("structure", 'method(name: *) as $m;', "matches"), ("patterns", "builder", "findings"), ("bugs", "", "findings")])
def test_mcp_find_uses_same_engine(tmp_path, monkeypatch, scope, query, key):
    (tmp_path / "a.py").write_text(PYTHON["builder"] + "\ndef bad(values=[]): return values\n")
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    result = server.ken_find(query, scope=scope, cache_mb=0)
    assert result[key]
    assert "analysis" in result


def test_mcp_schema_exposes_structural_scopes_and_cache():
    tool = next(t for t in server.list_tools() if t.name == "ken_find")
    properties = tool.parameters["properties"]
    assert {"structure", "patterns", "bugs"} <= set(properties["scope"]["enum"])
    assert properties["cache_mb"]["type"] == "number"
