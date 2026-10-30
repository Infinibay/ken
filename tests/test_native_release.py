"""Source-to-artifact binding uses actual small native builds, without models."""
from pathlib import Path
import hashlib, json, shutil, subprocess
import pytest


def repository(root, *, mutating=False):
    root.mkdir()
    (root/'Cargo.toml').write_text('[workspace]\nresolver="2"\nmembers=["crates/ken-cli","crates/ken-checks-application"]\n')
    for package, names in [('ken-cli',['ken','ken-rs']),('ken-checks-application',['ken-check-worker'])]:
        directory=root/'crates'/package; directory.mkdir(parents=True)
        manifest=f'[package]\nname="{package}"\nversion="0.1.0"\nedition="2024"\n'
        for name in names:
            manifest+=f'[[bin]]\nname="{name}"\npath="{name}.rs"\n'
            (directory/(name+'.rs')).write_text('fn main(){println!("captured native source");}\n')
        (directory/'Cargo.toml').write_text(manifest)
    if mutating:
        (root/'crates/ken-cli/build.rs').write_text('use std::os::unix::fs::PermissionsExt;fn main(){std::fs::set_permissions("ken.rs",std::fs::Permissions::from_mode(0o644)).unwrap();std::fs::write("ken.rs", "fn main(){}\\n").unwrap();}\n')
    git=shutil.which('git'); subprocess.run([git,'init','-q',str(root)],check=True)
    subprocess.run([shutil.which('cargo'),'generate-lockfile','--offline'],cwd=root,check=True,capture_output=True)
    subprocess.run([git,'-C',str(root),'add','.'],check=True)
    return root


def test_actual_build_captures_uncommitted_sources_and_binds_all_three_native_executables(tmp_path):
    from tools.native_release import build_release, authenticate_build
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'
    source=repo/'crates/ken-cli/ken.rs'; source.write_text('fn main(){println!("new uncommitted implementation");}\n')
    report=build_release(repo,out)
    assert report['source']['files']['crates/ken-cli/ken.rs']==json.loads((out/'BUILD.json').read_text())['source']['files']['crates/ken-cli/ken.rs']
    assert set(report['artifacts'])=={'launcher','cli','check_worker'}
    assert subprocess.check_output([out/'artifacts/ken'],text=True).strip()=='new uncommitted implementation'
    source.write_text('fn main(){}\n')
    assert authenticate_build(out)['source']['sha256']==report['source']['sha256']
    assert not (out/'source/.git').exists()


def test_tampered_binary_or_exported_source_invalidates_the_build_binding(tmp_path):
    from tools.native_release import build_release, authenticate_build
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'; build_release(repo,out)
    binary=out/'artifacts/ken-rs'; binary.chmod(0o755); binary.write_bytes(binary.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='artifact'): authenticate_build(out)
    # A fresh candidate shows the source side is authenticated independently.
    out=tmp_path/'second'; build_release(repo,out)
    source=out/'source/Cargo.toml'; source.chmod(0o644); source.write_text(source.read_text()+'\n')
    with pytest.raises(ValueError,match='source'): authenticate_build(out)


def test_build_that_mutates_its_own_export_cannot_publish_a_binding(tmp_path):
    from tools.native_release import build_release
    repo=repository(tmp_path/'repo',mutating=True); out=tmp_path/'candidate'
    with pytest.raises(ValueError,match='source.*changed'): build_release(repo,out)
    assert not (out/'BUILD.json').exists()


def test_symlinked_build_input_is_rejected_before_running_cargo(tmp_path):
    from tools.native_release import build_release
    repo=repository(tmp_path/'repo'); source=repo/'crates/ken-cli/ken.rs'; source.unlink(); source.symlink_to('/etc/passwd')
    with pytest.raises(ValueError,match='source.*regular|source.*symlink'): build_release(repo,tmp_path/'candidate')
    assert not (tmp_path/'candidate/cargo-stdout.jsonl').exists()


def test_existing_output_and_nonabsolute_compiler_are_rejected_without_overwriting(tmp_path):
    from tools.native_release import build_release
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'; out.mkdir(); (out/'foreign').write_text('keep')
    with pytest.raises(ValueError): build_release(repo,out)
    assert (out/'foreign').read_text()=='keep'
    with pytest.raises(ValueError,match='absolute'): build_release(repo,tmp_path/'second',cargo_program=Path('cargo'))


def test_changed_invocation_cannot_authenticate_as_a_successful_source_bound_build(tmp_path):
    from tools.native_release import build_release, authenticate_build
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'; build_release(repo,out)
    path=out/'BUILD.json'; receipt=json.loads(path.read_text());receipt['build']['command']=['/bin/true'];path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='invocation'): authenticate_build(out)


def test_package_binding_rechecks_every_binary_instead_of_accepting_a_supplied_flag(tmp_path):
    from tools.native_release import build_release, bind_build
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'; report=build_release(repo,out)
    binaries={role:out/row['path'] for role,row in report['artifacts'].items()}
    binding=bind_build(out,binaries)
    assert binding['source_sha256']==report['source']['sha256']
    assert binding['receipt']=={'bytes':(out/'BUILD.json').stat().st_size,'sha256':hashlib.sha256((out/'BUILD.json').read_bytes()).hexdigest()}
    binaries['cli']=Path('/bin/true')
    with pytest.raises(ValueError,match='artifact'): bind_build(out,binaries)


def test_binding_returns_the_compared_artifact_identity_for_later_staging(tmp_path,monkeypatch):
    from tools import native_release
    repo=repository(tmp_path/'repo'); out=tmp_path/'candidate'; report=native_release.build_release(repo,out)
    binaries={role:out/row['path'] for role,row in report['artifacts'].items()}
    candidate=tmp_path/'candidate-ken';shutil.copyfile(binaries['launcher'],candidate);binaries['launcher']=candidate
    identity=native_release.identity
    changed=False
    def mutate_after_comparison(path):
        nonlocal changed
        record=identity(path)
        if Path(path)==candidate and not changed:
            candidate.write_bytes(candidate.read_bytes()+b'changed after comparison');changed=True
        return record
    monkeypatch.setattr(native_release,'identity',mutate_after_comparison)
    binding=native_release.bind_build(out,binaries)
    assert changed
    assert binding['artifacts']['launcher']=={key:report['artifacts']['launcher'][key] for key in ('bytes','sha256')}
    assert identity(candidate)!=binding['artifacts']['launcher']
