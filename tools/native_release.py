"""Build native release executables from a retained, authenticated source export.

Python coordinates the build only; the resulting three programs are native ELF.
The receipt binds this invocation and source export, not behavioral qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess

from tools.rust_migration.native_binary import check_native_architecture
from tools.rust_migration.native_json import identity, load, tree

ROLES = {'launcher': 'ken', 'cli': 'ken-rs', 'check_worker': 'ken-check-worker'}
BUILD_ROOTS = {'crates', 'native', 'src', 'vendor', '.cargo'}
CARGO_ARGUMENTS = ['build', '--locked', '--offline', '--release', '--message-format=json-render-diagnostics', '-p', 'ken-cli', '-p', 'ken-checks-application', '--bins']
BUILD_FILES = {'Cargo.toml', 'Cargo.lock', 'rust-toolchain', 'rust-toolchain.toml', 'build.rs'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _program(path, name):
    path = Path(path if path is not None else shutil.which(name) or '')
    if not path.is_absolute():
        raise ValueError(f'absolute {name} program required')
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'executable {name} program required')
    return path


def _relative(name):
    path = PurePosixPath(name)
    if not name or '\x00' in name or '\\' in name or path.is_absolute() or '..' in path.parts or str(path) != name:
        raise ValueError('confined relative build path required')
    return Path(name)


def _regular_source(root, name):
    path = root
    for part in _relative(name).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('source symlink is not a regular build input')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('source must be a regular file')
    return path


def _source_tree(root):
    files = tree(root, strict=True)
    if not files or len(files) > 40000 or sum(row['bytes'] for row in files.values()) > 1024**3:
        raise ValueError('source export exceeds bounded inventory')
    return files


def _source_names(repo, git):
    result = subprocess.run([git, '-C', repo, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], capture_output=True, check=True)
    names = set()
    for raw in result.stdout.split(b'\0'):
        if not raw:
            continue
        name = raw.decode('utf-8')
        path = _relative(name)
        if path.parts[0] in BUILD_ROOTS or name in BUILD_FILES:
            names.add(name)
    if not {'Cargo.toml', 'Cargo.lock'} <= names:
        raise ValueError('locked workspace source required')
    return sorted(names)


def _build_artifacts(stdout, source, target_directory):
    found = {}
    finished = False
    with stdout.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row.get('reason') == 'build-finished':
                finished = row.get('success') is True
            if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('kind') != ['bin']:
                continue
            name = row['target']['name']
            if name not in ROLES.values():
                continue
            package = 'ken-checks-application' if name == 'ken-check-worker' else 'ken-cli'
            if Path(row['manifest_path']).resolve() != source / 'crates' / package / 'Cargo.toml':
                raise ValueError('native artifact belongs to a different source manifest')
            binary = Path(row['executable']).resolve(strict=True)
            if name in found or not binary.is_relative_to(target_directory) or not binary.is_file():
                raise ValueError('native artifact is duplicated or outside owned target')
            check_native_architecture(binary, ('linux', 'x86_64'))
            found[name] = binary
    if not finished or set(found) != set(ROLES.values()):
        raise ValueError('all three successful native artifacts required')
    return found


def build_release(repo, destination, *, cargo_program=None, rustc_program=None, git_program=None, environment=None):
    """Retain exact sources, build outside the checkout, then publish one receipt."""
    repo = Path(repo).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('fresh native build destination required')
    cargo = _program(cargo_program, 'cargo')
    rustc = _program(rustc_program, 'rustc')
    git = _program(git_program, 'git')
    names = _source_names(repo, git)
    inputs = {name: identity(_regular_source(repo, name)) for name in names}
    if len(inputs) > 40000 or sum(row['bytes'] for row in inputs.values()) > 1024**3:
        raise ValueError('source export exceeds bounded inventory')
    destination.mkdir(parents=True)
    source = destination / 'source'
    source.mkdir()
    for name, expected in inputs.items():
        original = _regular_source(repo, name)
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with original.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        if identity(target) != expected or identity(original) != expected:
            raise ValueError('source changed during export')
        target.chmod(0o555 if os.access(original, os.X_OK) else 0o444)
    if _source_tree(source) != inputs:
        raise ValueError('source changed during export')
    command = [str(cargo), *CARGO_ARGUMENTS]
    env = dict(os.environ if environment is None else environment)
    # A shared target/cache could return artifacts compiled against other inputs.
    env.update(CARGO_TARGET_DIR=str(destination / 'target'), RUSTC=str(rustc))
    for key in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_RUSTC_WRAPPER'):
        env.pop(key, None)
    stdout = destination / 'cargo-stdout.jsonl'
    stderr = destination / 'cargo-stderr.log'
    with stdout.open('xb') as output, stderr.open('xb') as errors:
        result = subprocess.run(command, cwd=source, env=env, stdout=output, stderr=errors, timeout=7200, check=False)
    if _source_tree(source) != inputs:
        raise ValueError('source export changed during build')
    if result.returncode:
        raise ValueError(f'native build failed with exit {result.returncode}; retained cargo-stderr.log')
    if stdout.stat().st_size > 64*1024**2 or stderr.stat().st_size > 64*1024**2:
        raise ValueError('native build log exceeds64MiB')
    found = _build_artifacts(stdout, source, destination/'target')
    artifacts = destination / 'artifacts'
    artifacts.mkdir()
    records = {}
    for role, name in ROLES.items():
        target = artifacts / name
        shutil.copyfile(found[name], target)
        target.chmod(0o555)
        records[role] = {'path': 'artifacts/' + name, **identity(target)}
    revision = subprocess.run([git, '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=False)
    dirty = subprocess.run([git, '-C', repo, 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, check=True)
    tools = {name: {'path': str(path), **identity(path), 'version': subprocess.check_output([path, '--version'], text=True).strip()} for name, path in [('cargo', cargo), ('rustc', rustc)]}
    selected_env = {key: value for key, value in env.items() if key in {'CARGO_TARGET_DIR','RUSTC','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CC','CXX','AR','CFLAGS','CXXFLAGS','CARGO_BUILD_JOBS','CMAKE_PARALLEL'}}
    receipt = {'format': 'ken-native-build/1', 'source': {'commit': revision.stdout.strip() if revision.returncode == 0 else None, 'dirty': bool(dirty.stdout), 'sha256': _digest(inputs), 'files': inputs}, 'build': {'command': command, 'cwd': 'source', 'tools': tools, 'environment': selected_env, 'stdout': identity(stdout), 'stderr': identity(stderr)}, 'artifacts': records}
    (destination/'BUILD.json').write_text(json.dumps(receipt, sort_keys=True, indent=2)+'\n')
    return authenticate_build(destination)


def authenticate_build(directory):
    """Recheck retained source, invocation logs and exact resulting native bytes."""
    directory = Path(directory).resolve(strict=True)
    receipt = load(directory/'BUILD.json')
    if set(receipt) != {'format','source','build','artifacts'} or receipt['format'] != 'ken-native-build/1':
        raise ValueError('native build receipt required')
    source = receipt['source']
    if _source_tree(directory/'source') != source['files'] or _digest(source['files']) != source['sha256']:
        raise ValueError('native build source identity differs')
    if set(receipt['artifacts']) != set(ROLES):
        raise ValueError('native artifact role inventory differs')
    if set(tree(directory/'artifacts',strict=True)) != set(ROLES.values()):
        raise ValueError('native artifact inventory differs')
    for role, name in ROLES.items():
        row = receipt['artifacts'][role]
        if set(row) != {'path','bytes','sha256'} or row['path'] != 'artifacts/'+name or identity(directory/row['path']) != {key:row[key] for key in ('bytes','sha256')}:
            raise ValueError('native artifact identity differs')
        check_native_architecture(directory/row['path'], ('linux','x86_64'))
    build = receipt['build']
    cargo = build['tools']['cargo']['path']
    if not Path(cargo).is_absolute() or build['command'] != [cargo, *CARGO_ARGUMENTS] or build['cwd'] != 'source':
        raise ValueError('native build invocation differs')
    found = _build_artifacts(directory/'cargo-stdout.jsonl', directory/'source', directory/'target')
    for role,name in ROLES.items():
        if identity(found[name]) != identity(directory/receipt['artifacts'][role]['path']):
            raise ValueError('native artifact does not match captured Cargo output')
    for name,key in [('cargo-stdout.jsonl','stdout'),('cargo-stderr.log','stderr')]:
        if identity(directory/name) != receipt['build'][key]:
            raise ValueError('native build invocation log identity differs')
    return receipt


def bind_build(directory, binaries):
    """Bind package inputs to all three outputs of an authenticated actual build."""
    directory = Path(directory).resolve(strict=True)
    receipt = authenticate_build(directory)
    artifacts = {}
    for role in ROLES:
        expected = {key:receipt['artifacts'][role][key] for key in ('bytes','sha256')}
        if role not in binaries or identity(Path(binaries[role])) != expected:
            raise ValueError('package artifact differs from captured native build')
        artifacts[role] = expected
    return {'receipt': identity(directory/'BUILD.json'), 'source_sha256': receipt['source']['sha256'], 'source_commit': receipt['source']['commit'], 'source_dirty': receipt['source']['dirty'], 'artifacts': artifacts, 'scope': 'captured source and actual Cargo artifacts; no behavioral qualification'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args(argv)
    receipt=build_release(args.repo,args.destination)
    print(json.dumps({'build':str(args.destination/'BUILD.json'),'source_sha256':receipt['source']['sha256'],'artifacts':receipt['artifacts']},sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
