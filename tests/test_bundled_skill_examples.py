"""Exercise the regression skill's shipped definition through the public CLI."""

import json
import re
import subprocess
import sys

import pytest

from ken.cli import main
from ken.kql2.service import search
from ken.kql2.syntax import parse
from ken.skills.catalog import bundled_skills
from ken.skills.installation import install_skills


def test_shipped_contract_validates_and_detects_a_regression(tmp_path, capsys):
    bundle = bundled_skills()["ken-prevent-regressions"]
    definition = json.loads(bundle["references/return-contract.json"])
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/store.py"
    source.write_text(definition["examples"][0]["files"]["src/store.py"])
    main(["install", str(tmp_path), "--no-wire", "--quiet"])
    capsys.readouterr()

    def call(*args):
        assert main(["tools", "--path", str(tmp_path), *args]) == 0
        return json.loads(capsys.readouterr().out)

    call("rule", "--action", "create", "--definition", json.dumps(definition))
    validated = call("rule", "--action", "validate", "--rule-id", definition["id"])
    assert validated["state"] == "validated"
    call("rule", "--action", "enable", "--rule-id", definition["id"])
    before = call("check", "--rules", definition["id"])
    assert before["status"] == "pass"
    source.write_text(definition["examples"][1]["files"]["src/store.py"])
    after = call("check", "--rules", definition["id"], "--compare", before["run_id"])
    assert after["status"] == "fail"
    assert after["comparison"]["changes"][0]["change"] == "regression"


def _documented_programs():
    """Run the literal documentation, so an edited example cannot drift silently."""
    bundle = bundled_skills()["ken-find-code-patterns"]
    for path, data in bundle.items():
        if path.endswith(".md"):
            for source in re.findall(r"```kql\n(.*?)\n```", data.decode(), re.DOTALL):
                yield path, source


PROGRAMS = list(_documented_programs())
LIBRARIES = {
    parse(source).module: source for _, source in PROGRAMS if "\nquery " not in source
}
EXPECTED = {
    "publication_owners": [
        ["commit_then_publish"],
        ["publish_then_commit"],
        ["publish_only"],
        ["split_branches"],
        ["preview_update"],
    ],
    "actual_publication_owners": [
        ["commit_then_publish"],
        ["publish_then_commit"],
        ["publish_only"],
        ["split_branches"],
    ],
    "commit_before_replace": [["commit_then_publish"], ["preview_update"]],
    "confirmed_before_publication": [["commit_then_publish", 13, 14]],
    "handlers_with_continue": [[17, 18]],
    "handlers_without_raise": [[10], [17]],
    "literal_true_loops": [[21]],
    "explicit_return_none": [[29]],
    "wildcard_imports": [[34]],
    "named_calls": [["save_user"], ["discard_user"], ["overwrite_user"], ["write"]],
    "selected_methods": [["Writer", "write"]],
    "method_pairs": [["Writer", "write", "close"], ["Writer", "close", "write"]],
    "selected_wrappers": [["save_user"], ["discard_user"]],
    "missing_close": [["ReadOnly"]],
    "optional_close": [["ReadOnly"], ["Writer"]],
    "forwarded_result": [["save_user"]],
    "returned_target": [["save_user"]],
    "imported_writer": [["Writer", "write"]],
}


def _relationship_fixture(root, resources):
    (root / "src").mkdir(exist_ok=True)
    for path, content in resources.items():
        if path.startswith("references/kql2/relationships/") and path.endswith(
            ".py.txt"
        ):
            (root / "src" / path.rsplit("/", 1)[-1].removesuffix(".txt")).write_bytes(
                content
            )


@pytest.mark.parametrize(
    "path,source", [(path, source) for path, source in PROGRAMS if "\nquery " in source]
)
def test_documented_queries_distinguish_matches_from_near_misses(
    tmp_path, path, source
):
    resources = bundled_skills()["ken-find-code-patterns"]
    (tmp_path / "src").mkdir()
    syntax_only = path == "references/kql2/syntax.md"
    if path == "references/kql2/relationships.md":
        _relationship_fixture(tmp_path, resources)
    else:
        fixture = "syntax" if syntax_only else "sample"
        (tmp_path / "src/sample.py").write_bytes(
            resources[f"references/kql2/{fixture}.py.txt"]
        )
    result = search(
        tmp_path,
        source,
        path="src",
        libraries=LIBRARIES,
        cache_mb=0,
        backend="exploration" if syntax_only else "indexed",
    )
    assert result["complete"] and result["coverage_complete"], (path, result)
    assert result["unknown_candidates"] == 0
    assert not result["results_truncated"]
    name = re.search(r"\bquery (\w+)", source)[1]
    rows = result["rows"]
    if name == "mutable_defaults":
        assert len(rows) == 1
        assert "CALLABLE:bad_default" in rows[0][0]
        assert "HAZARD:mutable-default-argument" in rows[0][0]
    elif name == "method_targets":
        assert len(rows) == 1
        assert rows[0][0].endswith("CLASS:Writer")
        assert "CLASS:Writer/CALLABLE:write" in rows[0][1]
        assert "module/CALLABLE:save@" in rows[0][2]
    elif name == "save_without_close":
        assert len(rows) == 4
        assert {row[0].rsplit("CALLABLE:", 1)[1].split("@")[0] for row in rows} == {
            "save_user",
            "discard_user",
            "overwrite_user",
            "write",
        }
    else:
        normalized = [
            [value["name"] if isinstance(value, dict) else value for value in row]
            for row in rows
        ]
        assert sorted(normalized) == sorted(EXPECTED[name]), path
    if name == "optional_close":
        assert {item["status"] for item in result["optional_evidence"]} == {
            "matched",
            "absent",
        }


def test_violation_contract_rejects_bad_code_beside_a_good_example(tmp_path, capsys):
    bundle = bundled_skills()["ken-prevent-regressions"]
    definition = json.loads(bundle["references/mutable-default-contract.json"])
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/defaults.py"
    source.write_text(definition["examples"][0]["files"]["src/defaults.py"])
    assert main(["install", str(tmp_path), "--no-wire", "--quiet"]) == 0
    capsys.readouterr()

    def call(*args):
        assert main(["tools", "--path", str(tmp_path), *args]) == 0
        return json.loads(capsys.readouterr().out)

    call("rule", "--action", "create", "--definition", json.dumps(definition))
    validation = call("rule", "--action", "validate", "--rule-id", definition["id"])
    assert validation["state"] == "validated"
    call("rule", "--action", "enable", "--rule-id", definition["id"])
    before = call("check", "--rules", definition["id"])
    assert before["status"] == "pass"
    source.write_text(definition["examples"][3]["files"]["src/defaults.py"])
    after = call("check", "--rules", definition["id"], "--compare", before["run_id"])
    assert after["status"] == "fail"
    assert after["comparison"]["changes"][0]["change"] == "regression"


def test_installed_skills_have_self_contained_reference_links(tmp_path):
    """Follow references from an installed bundle, including the composed manual."""
    install_skills(tmp_path, codex=True)
    for name, resources in bundled_skills().items():
        root = tmp_path / ".agents/skills" / name
        for relative in resources:
            if not relative.endswith(".md"):
                continue
            document = root / relative
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
                if "://" in target or target.startswith("#"):
                    continue
                resolved = (document.parent / target.split("#")[0]).resolve()
                assert resolved.is_relative_to(root), (name, relative, target)
                assert resolved.is_file(), (name, relative, target)


def test_kql_authors_receive_identical_shared_resources():
    bundles = bundled_skills()
    pattern_reference = {
        key: value
        for key, value in bundles["ken-find-code-patterns"].items()
        if key.startswith("references/kql2/")
    }
    assert pattern_reference
    for author in ("ken-prevent-regressions", "ken-investigate-bug"):
        reference = {
            key: value
            for key, value in bundles[author].items()
            if key.startswith("references/kql2/")
        }
        assert pattern_reference == reference
    assert not any(
        key.startswith("references/kql2/")
        for name, resources in bundles.items()
        if name
        not in {
            "ken-find-code-patterns",
            "ken-prevent-regressions",
            "ken-investigate-bug",
        }
        for key in resources
    )


def test_relationship_recipe_preserves_witnesses_through_compact_mcp(
    tmp_path, monkeypatch
):
    from ken.mcp import server

    resources = bundled_skills()["ken-investigate-bug"]
    _relationship_fixture(tmp_path, resources)
    source = next(
        source
        for _, source in PROGRAMS
        if "query confirmed_before_publication" in source
    )
    monkeypatch.setattr(server, "_PROJECT_ROOT", tmp_path)
    result = server.ken_find(
        query=source, scope="structure", query_language="kql/2", path="src", cache_mb=0
    )
    assert result["rows"] == [["commit_then_publish", 13, 14]]
    assert result["complete"] and result["coverage_complete"]
    assert not result.get("diagnostics")


def test_documented_failure_injection_distinguishes_the_order(tmp_path):
    resources = bundled_skills()["ken-investigate-bug"]
    _relationship_fixture(tmp_path, resources)
    document = resources["references/kql2/relationships.md"].decode()
    example = next(
        source
        for source in re.findall(r"```python\n(.*?)\n```", document, re.DOTALL)
        if source.startswith("namespace = {}")
    )
    # Only execute the authored teaching fixture, never project source found by KQL.
    result = subprocess.run(
        [sys.executable, "-c", example],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [
        "commit_then_publish ['committed']",
        "publish_then_commit []",
    ]
