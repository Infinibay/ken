"""The default surface is meant to be read; --full keeps the auditable result.

A 60 finding pattern scan over one package serialized 1.5 MB, mostly evidence
trees, per-rule outcomes, directory rollups and a copy of each rule's query text
inside every finding. The default now answers what/where/how-confident and
``--full`` (CLI) or ``full=True`` (MCP) restores the verbatim payload.
"""
from __future__ import annotations

import json

from ken.cli import main
from ken.mcp import server

from .gof_sources import PYTHON

SOURCE = PYTHON["builder"]


def _cli(tmp_path, capsys, *extra):
    (tmp_path / "builder.py").write_text(SOURCE, encoding="utf-8")
    assert main(["structural", "patterns", "--path", str(tmp_path), "--cache-mb", "0", *extra]) == 0
    return json.loads(capsys.readouterr().out)


def test_patterns_default_is_a_summary_not_the_engine_dump(tmp_path, capsys):
    result = _cli(tmp_path, capsys)
    assert result["findings"]
    assert result["count"] == len(result["findings"])
    assert result["summary"]
    assert result["complete"] is True
    assert "outcomes" not in result and "directories" not in result
    finding = result["findings"][0]
    assert set(finding) <= {"pattern", "variant", "confidence", "path", "line", "symbol", "status", "unknown"}
    assert finding["pattern"] and finding["path"]
    assert 0 < finding["confidence"] <= 1
    assert isinstance(result["analysis"]["files"], int)
    assert result["note"]


def test_full_restores_the_evidence_and_agrees_on_the_findings(tmp_path, capsys):
    compact = _cli(tmp_path, capsys)
    full = _cli(tmp_path, capsys, "--full")
    assert full["outcomes"] and full["directories"]
    assert full["findings"][0]["evidence"]
    assert {f["pattern"] for f in compact["findings"]} == {f["id"] for f in full["findings"]}
    assert len(compact["findings"]) == len(full["findings"])


def test_compact_payload_is_far_smaller_than_the_verbatim_one(tmp_path, capsys):
    compact = json.dumps(_cli(tmp_path, capsys))
    full = json.dumps(_cli(tmp_path, capsys, "--full"))
    assert len(compact) * 4 < len(full)


def test_mcp_structural_scopes_are_compact_unless_full_is_asked(tmp_path, monkeypatch):
    (tmp_path / "builder.py").write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    compact = server.ken_find("builder", scope="patterns", cache_mb=0)
    assert compact["findings"] and "outcomes" not in compact
    full = server.ken_find("builder", scope="patterns", cache_mb=0, full=True)
    assert full["findings"] and full["outcomes"]


def test_structure_matches_keep_bindings_and_drop_evidence(tmp_path, capsys):
    (tmp_path / "a.py").write_text("class A:\n    def run(self):\n        return 1\n", encoding="utf-8")
    assert main(["structural", "search", "--path", str(tmp_path), "--cache-mb", "0",
                 "--query", 'method(name: /^run$/) as $m;']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["matches"] and result["matches"][0]["bindings"]
    assert "evidence" not in result["matches"][0]


def test_bug_findings_keep_their_message_and_severity(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def bad(values=[]):\n    return values\n", encoding="utf-8")
    assert main(["structural", "bugs", "--path", str(tmp_path), "--cache-mb", "0"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["findings"]
    finding = result["findings"][0]
    assert finding["rule"] and finding["severity"] and finding["message"]
    assert finding["path"] and "evidence" not in finding


def test_the_variant_is_named_even_when_it_hides_under_a_union_branch(tmp_path):
    """The union reports ``variant: default``; the variant lives in the evidence.

    A root query is ``any { match "...<variant>" } or { ... }``, so the branch
    that matched is nested under ``alternatives`` -- reading only the top level
    of the evidence silently reported every catalogue finding as ``default``.
    """
    import json as _json

    from ken.structural import report, service

    (tmp_path / "pool.py").write_text(
        "class Glyph:\n"
        "    def __init__(self, font): self.font = font\n"
        "class Pool:\n"
        "    def __init__(self): self.pool = {}\n"
        "    def key_for(self, state): return state\n"
        "    def get(self, state):\n"
        "        key = self.key_for(state)\n"
        "        if not self.pool.get(key):\n"
        "            self.pool[key] = Glyph(state)\n"
        "        return self.pool[key]\n", encoding="utf-8")
    result = service.patterns(tmp_path, ["flyweight"], path=".", cache_mb=0)
    assert result["findings"]
    compact = report.present(result, kind="patterns")
    assert compact["findings"][0]["pattern"] == "flyweight"
    assert compact["findings"][0]["variant"] == "explicit-interning"
