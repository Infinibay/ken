"""Source-contract lifecycle through the same API used by MCP and CLI."""

from copy import deepcopy
import json
import subprocess
import sys

import pytest

from ken.checks import execution, worker
from ken.checks.integration import freshness, related
from ken.checks.model import Rule, judgment
from ken.checks.rules import manage
from ken.checks.service import check
from ken.checks.store import Store


GOOD = 'def save():\n return 42\ndef save_user():\n """Save a user and return the identifier."""\n return save()\n'
BAD = GOOD.replace("return save()", "save()\n return 0")
QUERY = """language "kql/2"; module project.storage;
query returned_identifier {
 callable $owner { name: "save_user"; body {
   let $value = call $save { name: "save"; };
   return $value;
 } }
 select $owner;
}"""


@pytest.fixture
def contract(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/store.py").write_text(GOOD)
    definition = {
        "id": "storage.return-id",
        "query": QUERY,
        "description": "save_user returns the save call's value",
        "path": "src",
        "expectation": "some_match",
        "examples": [
            {"name": "returned", "files": {"src/store.py": GOOD}, "expect": "pass"},
            {"name": "discarded", "files": {"src/store.py": BAD}, "expect": "fail"},
        ],
    }
    manage(tmp_path, "create", definition=definition)
    return tmp_path, definition


def enable(root, *, automatic=False):
    validated = manage(root, "validate", rule_id="storage.return-id")
    assert validated["state"] == "validated", validated
    return manage(root, "enable", rule_id="storage.return-id", automatic=automatic)


def test_lifecycle_regression_resolution_and_readable_receipt(contract):
    root, definition = contract
    assert check(root)["status"] == "not_applicable"
    with pytest.raises(ValueError, match="validate"):
        manage(root, "enable", rule_id=definition["id"])
    enable(root)
    before = check(root, full=True)
    assert before["status"] == "pass"
    assert before["checks"][0]["query"] == QUERY
    (root / "src/store.py").write_text(BAD)
    after = check(root, compare=before["run_id"])
    assert after["status"] == "fail"
    assert after["comparison"]["changes"][0]["change"] == "regression"
    (root / "src/store.py").write_text(GOOD)
    fixed = check(root, compare=after["run_id"])
    assert fixed["comparison"]["changes"][0]["change"] == "resolved"
    assert check(root, run_id=before["run_id"], full=True) == before
    assert Store(root).path("runs", before["run_id"]).is_file()


def test_restart_and_warm_result_reuse(contract):
    root, _ = contract
    enable(root)
    before = check(root, full=True)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from pathlib import Path; from ken.checks.service import check; print(json.dumps(check(Path(sys.argv[1]),full=True)))",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(process.stdout)
    assert result["status"] == before["status"] == "pass"
    assert result["checks"][0]["result"]["analysis"]["result_cache"] == "disk_hit"


def test_update_invalidates_validation_and_disabled_rule_is_not_automatic(contract):
    root, definition = contract
    enable(root, automatic=True)
    changed = definition | {"description": "Revised expectation"}
    out = manage(root, "update", rule_id=definition["id"], definition=changed)
    assert out["state"] == "draft" and not out["automatic"]
    with pytest.raises(ValueError, match="validate"):
        manage(root, "enable", rule_id=definition["id"])
    enable(root)
    manage(root, "disable", rule_id=definition["id"])
    assert check(root, automatic=True)["checks"] == []
    assert check(root, rules=[definition["id"]])["status"] == "pass"


def test_validation_detects_incorrect_examples_and_requires_both_outcomes(contract):
    root, definition = contract
    wrong = deepcopy(definition)
    wrong["examples"][1]["files"]["src/store.py"] = GOOD
    manage(root, "update", rule_id=definition["id"], definition=wrong)
    result = manage(root, "validate", rule_id=definition["id"])
    assert result["state"] == "draft"
    assert not result["validation"]["passed"]
    wrong["examples"] = wrong["examples"][:1]
    manage(root, "update", rule_id=definition["id"], definition=wrong)
    with pytest.raises(ValueError, match="passing and failing"):
        manage(root, "validate", rule_id=definition["id"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "../outside"),
        ("path", "/outside"),
        ("id", "../oops"),
        ("expectation", "always"),
        ("query", "run shell"),
    ],
)
def test_invalid_definitions_are_rejected(contract, field, value):
    root, definition = contract
    with pytest.raises(ValueError):
        Rule.read(definition | {field: value})


def test_example_cannot_write_outside_its_temporary_project(contract):
    _, definition = contract
    broken = deepcopy(definition)
    broken["examples"][0]["files"] = {"../escape.py": "bad"}
    with pytest.raises(ValueError):
        Rule.read(broken)


@pytest.mark.parametrize(
    "patch",
    [
        {"complete": False},
        {"coverage_complete": False},
        {"unknown_candidates": 1},
        {"results_truncated": True},
        {"reason": "timeout"},
    ],
)
def test_incomplete_search_never_certifies_pass_or_failure(patch):
    for rows in ([], [[1]]):
        result = {
            "rows": rows,
            "complete": True,
            "coverage_complete": True,
            "unknown_candidates": 0,
            "results_truncated": False,
            "reason": None,
        } | patch
        for expectation in ("some_match", "no_matches"):
            assert judgment(result, expectation) == "unknown"


def test_real_timeout_and_unsupported_source_preserve_unknown(contract):
    root, definition = contract
    timed = check(root, rules=[definition["id"]], timeout_ms=1)
    assert timed["status"] == "unknown"
    assert timed["checks"][0]["reason"] == "timeout"
    (root / "src/native.c").write_text("int save_user(void) { return 1; }")
    result = check(root, rules=[definition["id"]])
    assert result["status"] == "unknown"
    assert result["checks"][0]["coverage_complete"] is False


def test_source_change_during_query_is_unknown(contract, monkeypatch):
    root, definition = contract
    from ken.kql2 import service

    original = service.search

    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        (root / "src/store.py").write_text(BAD)
        return result

    monkeypatch.setattr(service, "search", racing)
    result = worker.evaluate(
        {
            "root": str(root),
            "path": "src",
            "query": QUERY,
            "max_rows": 100,
            "timeout_ms": 10000,
        }
    )
    assert judgment(result, definition["expectation"]) == "unknown"
    assert result["reason"] == "source_changed_during_check"


def test_scope_selects_rules_without_narrowing_their_domain(contract):
    root, definition = contract
    (root / "src/other.py").write_text("x = 1")
    result = check(root, rules=[definition["id"]], path="src/other.py", full=True)
    assert result["status"] == "pass"
    assert result["checks"][0]["path"] == "src"
    assert (
        check(root, rules=[definition["id"]], path="docs")["status"] == "not_applicable"
    )


def test_new_deleted_and_edited_sources_invalidate_receipt(contract):
    root, definition = contract
    result = check(root, rules=[definition["id"]], full=True)
    assert freshness(root, result)["state"] == "unchanged"
    other = root / "src/new.py"
    other.write_text("x = 1")
    assert freshness(root, result)["state"] == "stale"
    other.unlink()
    assert freshness(root, result)["state"] == "unchanged"
    (root / "src/store.py").unlink()
    assert freshness(root, result)["state"] == "stale"


def test_changed_rule_or_engine_prevents_comparison(contract, monkeypatch):
    root, definition = contract
    before = check(root, rules=[definition["id"]], full=True)
    manage(
        root,
        "update",
        rule_id=definition["id"],
        definition=definition | {"description": "changed"},
    )
    assert freshness(root, before)["state"] == "stale"
    result = check(root, rules=[definition["id"]], compare=before["run_id"])
    assert result["comparison"]["changes"][0]["change"] == "not_comparable"


def test_unknown_cannot_be_reported_as_resolution(contract):
    root, definition = contract
    (root / "src/store.py").write_text(BAD)
    before = check(root, rules=[definition["id"]])
    assert before["status"] == "fail"
    after = check(
        root, rules=[definition["id"]], compare=before["run_id"], timeout_ms=1
    )
    assert after["comparison"]["changes"][0]["change"] == "inconclusive"


def test_changes_scope_includes_staged_unstaged_untracked_and_deleted(contract):
    root, definition = contract

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init")
    git("add", "src")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    assert (
        check(root, rules=[definition["id"]], scope="changes")["status"]
        == "not_applicable"
    )
    (root / "src/new.py").write_text("x = 1")
    assert check(root, rules=[definition["id"]], scope="changes")["status"] == "pass"
    git("add", "src/new.py")
    (root / "src/store.py").write_text(BAD)
    assert check(root, rules=[definition["id"]], scope="changes")["status"] == "fail"
    (root / "src/store.py").unlink()
    assert check(root, rules=[definition["id"]], scope="changes")["status"] == "fail"


def test_rules_and_receipts_are_related_without_new_queries(contract, monkeypatch):
    root, definition = contract
    check(root, rules=[definition["id"]])
    monkeypatch.setattr(
        execution, "run", lambda *a, **k: pytest.fail("must not execute KQL")
    )
    result = related(root, "src/store.py")
    assert result["rules"][0]["id"] == definition["id"]
    assert result["checks"][0]["validity"]["state"] == "unchanged"


def test_no_symlink_source_or_receipt_escape(contract, tmp_path):
    root, definition = contract
    (root / "src/link").symlink_to(root / "src", target_is_directory=True)
    result = check(root, rules=[definition["id"]])
    assert result["status"] == "unknown"
    assert "symlink" in result["checks"][0]["reason"]
    with pytest.raises(ValueError):
        Store(root).read("runs", "../escape")


def test_project_modules_are_never_imported_by_the_query_worker(contract, monkeypatch):
    root, definition = contract
    (root / "ken").mkdir()
    marker = root / "source-was-executed"
    (root / "ken/__init__.py").write_text(
        f"from pathlib import Path; Path({str(marker)!r}).touch(); raise RuntimeError('hijacked')"
    )
    (root / "sitecustomize.py").write_text(
        f"from pathlib import Path; Path({str(marker)!r}).touch()"
    )
    monkeypatch.chdir(root)
    monkeypatch.setenv("PYTHONPATH", str(root))
    assert check(root, rules=[definition["id"]])["status"] == "pass"
    assert not marker.exists()


def test_engine_change_requires_revalidation_instead_of_empty_success(
    contract, monkeypatch
):
    root, _ = contract
    enable(root)
    monkeypatch.setattr("ken.checks.service.engine_version", lambda: "changed engine")
    result = check(root)
    assert result["status"] == "unknown"
    assert result["checks"] == []
    assert result["skipped_rules"][0]["rule"] == "storage.return-id"


def test_no_matches_rule_detects_a_bug_family(contract):
    root, _ = contract
    query = """language "kql/2"; module project.bugs;
query mutable_defaults { edge HAS_HAZARD($site, "mutable-default-argument"); select $site; }"""
    definition = {
        "id": "python.mutable-default",
        "query": query,
        "description": "No mutable literal defaults in src",
        "path": "src",
        "examples": [
            {
                "name": "shared list",
                "files": {"src/a.py": "def f(items=[]): return items"},
                "expect": "fail",
            },
            {
                "name": "optional parameter",
                "files": {"src/a.py": "def f(items=None): return items"},
                "expect": "pass",
            },
        ],
    }
    manage(root, "create", definition=definition)
    assert manage(root, "validate", rule_id=definition["id"])["state"] == "validated"
    (root / "src/another.py").write_text(
        "def completely_different(options={}): return options"
    )
    result = check(root, rules=[definition["id"]])
    assert result["status"] == "fail"
    assert result["checks"][0]["witnesses"]


def test_catalog_library_change_invalidates_receipt(contract, monkeypatch):
    root, definition = contract
    result = check(root, rules=[definition["id"]], full=True)
    from ken.kql2 import catalog

    original = catalog.sources()
    monkeypatch.setattr(
        catalog, "sources", lambda: original + (("changed.toml", "changed library"),)
    )
    assert freshness(root, result)["state"] == "stale"


def test_rule_changed_during_execution_does_not_publish_a_current_pass(
    contract, monkeypatch
):
    root, definition = contract
    original = execution.run

    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        manage(
            root,
            "update",
            rule_id=definition["id"],
            definition=definition | {"description": "Changed while running"},
        )
        return result

    monkeypatch.setattr(execution, "run", racing)
    result = check(root, rules=[definition["id"]])
    assert result["status"] == "unknown"
    assert result["checks"][0]["reason"] == "rule_changed_during_check"
