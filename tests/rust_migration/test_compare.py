"""The comparator rejects matching failures, missing fields and type coercion."""
import json
from dataclasses import replace

import pytest

from tools.rust_migration.compare import Case, ProcessResult, compare_case, run_process


def result(data):
    return ProcessResult(["fixture"], 0, json.dumps(data) + "\n", "", 1)


def test_equal_invalid_outputs_are_not_success():
    case = Case("empty", "installed_empty", "json", [], 0, {})
    expected = {"ok": True, "installed": True, "counts": {"files": 0}}
    assert compare_case(case, expected, result({}), result({}))


@pytest.mark.parametrize("change", ["missing", "string", "boolean", "float", "order"])
def test_removed_key_changed_type_and_reordered_recommendations_fail(change):
    data = {"ok": True, "counts": {"files": 0}, "recommendations": ["first", "second"]}
    altered = json.loads(json.dumps(data))
    if change == "missing":
        del altered["counts"]
    elif change == "order":
        altered["recommendations"].reverse()
    else:
        altered["counts"]["files"] = {"string": "0", "boolean": False, "float": 0.0}[change]
    case = Case("empty", "installed_empty", "json", [], 0, data)
    assert compare_case(case, data, result(data), result(altered))


def test_only_declared_path_fields_are_normalized():
    a = {"project_root": "/a", "db": {"path": "/a/.ken/ken.db"}, "message": "/a/important"}
    b = {"project_root": "/b", "db": {"path": "/b/.ken/ken.db"}, "message": "/a/important"}
    case = Case("path", "metadata_only", "json", [], 0, a)
    assert compare_case(case, a, result(a), result(b)) == []
    b["message"] = "/b/important"
    assert compare_case(case, a, result(a), result(b))


def test_real_process_records_streams_exit_and_timeout(tmp_path):
    import os
    import sys
    out = run_process([sys.executable, "-c", "import sys;print('out');print('err',file=sys.stderr);sys.exit(3)"], tmp_path, dict(os.environ), 5)
    assert (out.returncode, out.stdout, out.stderr) == (3, "out\n", "err\n")
    timeout = run_process([sys.executable, "-c", "import time;time.sleep(10)"], tmp_path, dict(os.environ), .05)
    assert timeout.returncode == 124


def test_real_bad_subprocess_is_rejected(tmp_path):
    import os
    import sys
    out = run_process([sys.executable, "-c", "print('{}')"], tmp_path, dict(os.environ), 5)
    case = Case("bad-process", "installed_empty", "json", [], 0, {"ok": True})
    assert compare_case(case, case.expected, out, out)


def test_failure_identifies_the_field_and_rejects_non_object_reports():
    expected = {"counts": {"files": 3}}
    case = Case("field-control", "installed_empty", "json", [], 0, expected)
    errors = compare_case(case, expected, result(expected), result({"counts": {"files": "3"}}))
    assert any("counts.files" in error for error in errors)
    for value in [[], None, 3, "report"]:
        assert compare_case(case, expected, result(expected), result(value))


def test_native_child_attempt_is_detected():
    import sys
    from pathlib import Path
    from tools.rust_migration.compare import run_case
    from tools.rust_migration.reference import Reference
    root=Path(__file__).resolve().parents[2]
    ref=Reference(root,root/"docs/validation/rust-migration-2026-10-18/baseline.json","test",Path(sys.executable))
    case=Case("child-control","installed_empty","json",[],0,{})
    result=run_case(case,ref,["/bin/sh","-c","python --version >/dev/null 2>&1; printf '{}\\n'"])
    assert any("forbidden child" in e for e in result["errors"])
