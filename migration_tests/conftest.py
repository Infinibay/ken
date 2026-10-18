"""Explicit native-binary tests: no compiler invocation or Python fallback."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.rust_migration.reference import Reference,reference_env,verify_reference

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope="session")
def native_binary():
    value=os.environ.get("KEN_RUST_BIN","")
    binary=Path(value)
    if not value or not binary.is_absolute() or not binary.is_file() or not os.access(binary,os.X_OK):
        pytest.fail("KEN_RUST_BIN must name an absolute, executable native binary; build it before testing")
    return binary

@pytest.fixture(scope="session")
def reference(tmp_path_factory):
    ref=Reference.load(Path(os.environ.get("KEN_RUST_REFERENCE",ROOT/".ken/rust-migration/m0-m1/reference")))
    assert verify_reference(ref.root,ref.manifest_path)==[]
    sandbox=tmp_path_factory.mktemp("oracle-import")
    out=subprocess.run([str(ref.python),"-c","import json,ken;print(json.dumps(ken.__file__))"],cwd=sandbox,env=reference_env(ref,sandbox),capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stderr
    assert Path(json.loads(out.stdout)).is_relative_to(ref.root)
    return ref
