import json
import platform
import shutil
import subprocess

from tools.rust_migration.compare import Case,run_case,run_process
from tools.rust_migration.fixtures import build_fixture
from tools.rust_migration.reference import reference_env

def test_runs_with_python_removed_from_path(reference,native_binary,tmp_path):
    copied=tmp_path/"ken-rs";shutil.copy2(native_binary,copied)
    empty=tmp_path/"empty-path";empty.mkdir()
    with build_fixture(tmp_path/"data","populated",reference) as f:
        env=reference_env(reference,tmp_path/"env");env["PATH"]=str(empty)
        out=run_process([str(copied),"status",str(f.root),"--json"],tmp_path,env,10)
        assert out.returncode==0 and not out.stderr,out
        assert json.loads(out.stdout)["counts"]["files"]==1
        assert f.changed()==[]

def test_runtime_does_not_execute_children(reference,native_binary):
    result=run_case(Case("native-runtime","installed_empty","json",[],0,{}),reference,[str(native_binary)])
    assert result["passed"] and result["native_children"]==[],result
    command=["otool","-L",str(native_binary)] if platform.system()=="Darwin" else ["ldd",str(native_binary)]
    linked=subprocess.run(command,capture_output=True,text=True,timeout=30)
    assert linked.returncode==0,linked.stderr
    assert "python" not in linked.stdout.lower()

def test_version_matches_reference(reference,native_binary,tmp_path):
    env=reference_env(reference,tmp_path)
    original=run_process([str(reference.python),"-m","ken","--version"],tmp_path,env,10)
    native=run_process([str(native_binary),"--version"],tmp_path,env,10)
    assert original.returncode==native.returncode==0
    assert original.stdout.split()[-1]==native.stdout.split()[-1]
