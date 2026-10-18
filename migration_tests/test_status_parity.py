import json
from pathlib import Path

import pytest

from tools.rust_migration.compare import Case,run_case

ROOT=Path(__file__).resolve().parents[1]
CASES=[Case(**row) for row in json.loads((ROOT/"docs/validation/rust-migration-2026-10-18/m0/m1-cases.json").read_text())["cases"]]

@pytest.mark.parametrize("case",CASES,ids=lambda c:c.id)
def test_status_public_case(case,reference,native_binary):
    result=run_case(case,reference,[str(native_binary)])
    assert result["native"]["returncode"]==case.expected_exit,result
    assert result["passed"],result
    assert "fixture-token" not in result["native"]["stderr"]

def test_wal_and_metadata_remain_logically_unchanged(reference,native_binary):
    result=run_case(next(c for c in CASES if c.id=="wal-json"),reference,[str(native_binary)])
    assert result["passed"],result
    assert result["native_children"]==[]
