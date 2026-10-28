"""The complete shared validation contract follows actual pytest discovery."""
from pathlib import Path
import subprocess,sys

def test_declared_native_core_roots_match_the_complete_discovered_scope():
    from tools.rust_migration.native_core_gates import test_files,PYTHON_ROOTS
    repo=Path(__file__).resolve().parents[2];files=test_files(repo)
    result=subprocess.run([sys.executable,'-m','pytest','-o','addopts=','-q','--collect-only',*files],
        cwd=repo,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    found=[line for line in result.stdout.splitlines()if any(line.startswith(name+'::')for name in files)]
    assert len(found)==len(set(found))==PYTHON_ROOTS,result.stdout
