"""Portable restoration authenticates original bytes before touching destinations."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from tools.rust_migration.portable_reference import restore_portable
from tools.rust_migration.reference import verify_reference


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(capsule, manifest, name, entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as target:
        for path, raw in entries:
            member = tarfile.TarInfo(path)
            member.size = len(raw)
            target.addfile(member, io.BytesIO(raw))
    raw = stream.getvalue()
    (capsule / name).write_bytes(raw)
    manifest['archives'][name] = dict(bytes=len(raw), sha256=sha(raw))


@pytest.fixture
def portable(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    capsule = repo / 'capsule'
    capsule.mkdir()
    sources = {'src/ken/__init__.py': b"MARKER = 'git'\n", 'src/ken/dirty.py': b"MARKER = 'dirty'\n"}
    records = []
    for index, (name, raw) in enumerate(sources.items()):
        blob = subprocess.check_output(['git', 'hash-object', '-w', '--stdin'], input=raw, cwd=repo).decode().strip() if index == 0 else None
        records.append(dict(path=name, bytes=len(raw), sha256=sha(raw), git_blob=blob))
    reference_records = [{k: r[k] for k in ('path', 'sha256')} for r in records]
    baseline = json.dumps(dict(scope=['src/ken/**'], files=reference_records)).encode()
    (repo / 'baseline.json').write_bytes(baseline)
    progress = b'# saved progress\nTask 2: complete\n'
    manifest = dict(format='ken-rust-handoff/1', baseline=dict(path='baseline.json', sha256=sha(baseline)),
        portable_reference_fingerprint=sha(json.dumps(reference_records, sort_keys=True).encode()),
        reference_files=records, override_files=['src/ken/dirty.py'],
        sdd_files=[dict(path='progress.md', bytes=len(progress), sha256=sha(progress))], archives={})
    archive(capsule, manifest, 'original-overrides.tar.gz', [('src/ken/dirty.py', sources['src/ken/dirty.py'])])
    archive(capsule, manifest, 'm4c2-progress.tar.gz', [('progress.md', progress)])
    return repo, capsule, manifest, sources


def restore(portable):
    repo, capsule, manifest, _ = portable
    (capsule / 'PORTABLE.json').write_text(json.dumps(manifest))
    return restore_portable(repo, capsule, reference=repo/'reference', progress=repo/'progress', python=Path(sys.executable))


def test_restores_git_objects_dirty_overrides_and_progress_without_editing_checkout(portable):
    repo, _, manifest, sources = portable
    result = restore(portable)
    assert result.reference.fingerprint == manifest['portable_reference_fingerprint']
    assert result.reference.python == Path(sys.executable).absolute()
    assert not verify_reference(result.reference.root, repo/'baseline.json')
    for name, raw in sources.items():
        assert (result.reference.root/name).read_bytes() == raw
        assert not (repo/name).exists()
    assert (result.progress/'progress.md').read_bytes().endswith(b'Task 2: complete\n')


@pytest.mark.parametrize('change', ['baseline', 'archive', 'git-object', 'fingerprint', 'missing-progress', 'duplicate-progress', 'unsafe-path'])
def test_corruption_is_rejected_before_any_destination_is_written(portable, change):
    repo, capsule, manifest, _ = portable
    if change == 'baseline':
        (repo/'baseline.json').write_bytes(b'changed')
    elif change == 'archive':
        (capsule/'original-overrides.tar.gz').write_bytes(b'changed')
    elif change == 'git-object':
        manifest['reference_files'][0]['sha256'] = '0'*64
    elif change == 'fingerprint':
        manifest['portable_reference_fingerprint'] = '0'*64
    elif change == 'missing-progress':
        archive(capsule, manifest, 'm4c2-progress.tar.gz', [])
    elif change == 'duplicate-progress':
        archive(capsule, manifest, 'm4c2-progress.tar.gz', [('progress.md', b'a'), ('progress.md', b'b')])
    else:
        archive(capsule, manifest, 'm4c2-progress.tar.gz', [('../outside', b'escape')])
    with pytest.raises(ValueError):
        restore(portable)
    assert not (repo/'reference').exists()
    assert not (repo/'progress').exists()
    assert not (repo/'outside').exists()


@pytest.mark.parametrize('existing', ['reference', 'progress'])
def test_never_overwrites_existing_originals_or_progress(portable, existing):
    repo, _, _, _ = portable
    destination = repo/existing
    destination.mkdir()
    (destination/'keep').write_bytes(b'prior work')
    with pytest.raises(FileExistsError):
        restore(portable)
    assert (destination/'keep').read_bytes() == b'prior work'
    assert not (repo/('progress' if existing=='reference' else 'reference')).exists()
