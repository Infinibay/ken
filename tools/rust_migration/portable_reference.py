"""Restore authenticated frozen originals and progress without changing source."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from .reference import Reference


@dataclass(frozen=True)
class PortableRestore:
    reference: Reference
    progress: Path


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(name: str) -> str:
    path = PurePosixPath(name)
    if not name or '\x00' in name or path.is_absolute() or '..' in path.parts or path.as_posix() != name:
        raise ValueError('unsafe portable path: ' + repr(name))
    return name


def _archive(path: Path, expected: dict) -> dict[str, bytes]:
    raw = path.read_bytes()
    if len(raw) != expected['bytes'] or _sha(raw) != expected['sha256']:
        raise ValueError('portable archive identity differs: ' + path.name)
    records = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            for member in archive:
                name = _path(member.name)
                if not member.isfile() or name in records:
                    raise ValueError('non-file or duplicated portable member: ' + name)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError('missing portable member: ' + name)
                records[name] = stream.read()
    except tarfile.TarError as error:
        raise ValueError('invalid portable archive: ' + path.name) from error
    return records


def _verify_files(rows: list[dict], contents: dict[str, bytes]) -> None:
    names = [_path(row['path']) for row in rows]
    if len(names) != len(set(names)) or set(names) != set(contents):
        raise ValueError('portable file inventory differs')
    for row in rows:
        raw = contents[row['path']]
        if len(raw) != row['bytes'] or _sha(raw) != row['sha256']:
            raise ValueError('portable content identity differs: ' + row['path'])


def _write_files(root: Path, contents: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    for name, raw in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def restore_portable(repo: Path, capsule: Path, *, reference: Path, progress: Path, python: Path) -> PortableRestore:
    """Authenticate all inputs first; neither destination may already exist."""
    repo, capsule = repo.absolute(), capsule.absolute()
    reference, progress = reference.absolute(), progress.absolute()
    for destination in (reference, progress):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(destination)
    if reference.is_relative_to(progress) or progress.is_relative_to(reference):
        raise ValueError('portable destinations must be independent')
    manifest = json.loads((capsule / 'PORTABLE.json').read_bytes())
    if manifest['format'] != 'ken-rust-handoff/1':
        raise ValueError('unsupported portable handoff')
    baseline = manifest['baseline']
    if _sha((repo / _path(baseline['path'])).read_bytes()) != baseline['sha256']:
        raise ValueError('portable baseline identity differs')
    archives = manifest['archives']
    if set(archives) != {'original-overrides.tar.gz', 'm4c2-progress.tar.gz'}:
        raise ValueError('portable archive inventory differs')
    overrides = _archive(capsule / 'original-overrides.tar.gz', archives['original-overrides.tar.gz'])
    saved = _archive(capsule / 'm4c2-progress.tar.gz', archives['m4c2-progress.tar.gz'])
    required_overrides = {row['path'] for row in manifest['reference_files'] if row['git_blob'] is None}
    if set(overrides) != set(manifest['override_files']) or set(overrides) != required_overrides:
        raise ValueError('portable override inventory differs')
    contents = {}
    records = []
    for row in manifest['reference_files']:
        name = _path(row['path'])
        if name in contents:
            raise ValueError('duplicated portable original: ' + name)
        blob = row['git_blob']
        if blob is None:
            raw = overrides[name]
        else:
            if not isinstance(blob, str) or len(blob) != 40 or any(c not in '0123456789abcdef' for c in blob):
                raise ValueError('invalid portable Git object')
            try:
                raw = subprocess.run(['git', 'cat-file', 'blob', blob], cwd=repo, check=True, capture_output=True).stdout
            except subprocess.CalledProcessError as error:
                raise ValueError('portable Git object unavailable: ' + blob) from error
        contents[name] = raw
        records.append({'path': name, 'sha256': row['sha256']})
    _verify_files(manifest['reference_files'], contents)
    _verify_files(manifest['sdd_files'], saved)
    fingerprint = _sha(json.dumps(records, sort_keys=True).encode())
    if fingerprint != manifest['portable_reference_fingerprint']:
        raise ValueError('portable fingerprint differs')
    metadata = dict(format='ken-rust-oracle/1', scope=['src/ken/**'], fingerprint=fingerprint,
                    python=str(python.absolute()), files=records)
    contents['reference-manifest.json'] = (json.dumps(metadata, indent=2) + '\n').encode()
    _write_files(reference, contents)
    _write_files(progress, saved)
    return PortableRestore(Reference.load(reference), progress)
