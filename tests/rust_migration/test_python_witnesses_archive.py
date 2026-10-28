from pathlib import Path
import base64,hashlib,json,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_git_authenticated_sources_reject_resealed_code_or_missing_tree(tmp_path):
    from tools.rust_migration.python_witnesses_archive import git_proof,verify_git_proof
    name='tools/rust_migration/python_witnesses_reference.py'
    revision='c808b269e56eb45efb8d28ba1245215b10f29dff'
    raw=subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT)
    p=tmp_path/name;p.parent.mkdir(parents=True);p.write_bytes(raw)
    proof=git_proof(ROOT,revision,[name]);assert not verify_git_proof(tmp_path,proof)
    p.write_bytes(raw+b'\n');assert verify_git_proof(tmp_path,proof)
    p.write_bytes(raw);proof['trees'].clear();assert verify_git_proof(tmp_path,proof)

def test_foreign_git_commit_and_source_inventory_reject(tmp_path):
    from tools.rust_migration.python_witnesses_archive import git_proof,verify_git_proof
    name='Cargo.toml';revision='c808b269e56eb45efb8d28ba1245215b10f29dff'
    (tmp_path/name).write_bytes(subprocess.check_output(['git','show',revision+':'+name],cwd=ROOT))
    proof=git_proof(ROOT,revision,[name]);assert not verify_git_proof(tmp_path,proof)
    proof['commit']='0'*40;assert verify_git_proof(tmp_path,proof)
    proof['commit']=revision;proof['sources'].append('../outside');assert verify_git_proof(tmp_path,proof)
