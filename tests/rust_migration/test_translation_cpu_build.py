"""The native module build binds actual SDK inputs and source bytes."""
from pathlib import Path
import os
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_missing_sdk_is_rejected_before_compilation_or_publication(tmp_path):
    from tools.rust_migration.translation_cpu_build import build
    with pytest.raises(ValueError,match='SDK'):
        build(ROOT,tmp_path/'missing',tmp_path/'out',cmake=tmp_path/'missing-cmake')
    assert not(tmp_path/'out').exists()

def test_actual_module_build_authenticates_sources_sdk_and_binary(tmp_path):
    from tools.rust_migration.translation_cpu_build import build,verify_build
    from tools.rust_migration.native_json import identity
    sdk=Path(os.environ['KEN_CT2_SDK']);out=tmp_path/'backend'
    report=build(ROOT,sdk,out,cmake=Path(os.environ['CMAKE']))
    assert not verify_build(out,ROOT,sdk)
    assert report['registration']['runtimes'][0]['module']==identity(Path(report['module_path']))
    assert report['registration']['runtimes'][0]['abi']==1
    assert report['core_root']==str(sdk/'lib')
    (out/'build/libken_ct2_backend.so').write_bytes(b'changed native module')
    assert verify_build(out,ROOT,sdk)
