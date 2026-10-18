"""Revision admission, including aliases and complete fallback monitoring."""

import os
import select

import pytest

from ken.kql2.host import QueryHost
from ken.kql2.revision import RevisionMonitor, SourceRevision

QUERY = 'language "kql/2"; module monitor; query q {class $c {name:"Worker";} select $c.name;}'


@pytest.mark.parametrize('kind', ['directory', 'file', 'child'])
def test_replacing_a_nested_scope_alias_refreshes_without_async_watcher(tmp_path, kind):
    for name, text in [('one', 'Worker'), ('two', 'Other')]:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'a.py').write_text(f'class {text}: pass\n')
    (tmp_path / 'deep').mkdir()
    alias = tmp_path / 'deep/alias'
    suffix = '/a.py' if kind == 'file' else ''
    scope = 'deep/alias/a.py' if kind == 'child' else 'deep/alias'
    alias.symlink_to(tmp_path / ('one' + suffix))
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY, path=scope)['rows'] == [['Worker']]
        alias.unlink()
        alias.symlink_to(tmp_path / ('two' + suffix))
        result = host.search(QUERY, path=scope)
        assert result['complete'] is True
        assert result['rows'] == []


def test_descriptor_limit_fallback_closes_partial_registration(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    revision = SourceRevision.capture(tmp_path, '.')
    opened = []
    original = os.open
    def open_one(*args, **kwargs):
        if opened:
            raise OSError('descriptor limit reached')
        fd = original(*args, **kwargs)
        opened.append(fd)
        return fd
    monkeypatch.setattr(os, 'open', open_one)
    monitor = RevisionMonitor(revision)
    try:
        assert monitor.backend == 'metadata'
        assert monitor.unchanged()
        if opened:
            with pytest.raises(OSError):
                os.fstat(opened[0])
        (tmp_path / 'a.py').write_text('class Other: pass\n')
        assert not monitor.unchanged()
    finally:
        monitor.close()


def test_missing_config_parent_is_watched_and_close_releases_descriptors(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    (tmp_path / '.ken').mkdir()
    revision = SourceRevision.capture(tmp_path, 'a.py')
    monitor = RevisionMonitor(revision)
    descriptors = list(monitor._fds)
    if hasattr(select, 'kqueue'):
        assert monitor.backend == 'kernel_vnode'
    assert monitor.unchanged()
    (tmp_path / '.ken/structural.json').write_text('{"cache_mb":1000}\n')
    assert not monitor.unchanged()
    assert not monitor.unchanged()  # Event consumption cannot resurrect a revision.
    monitor.close()
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)
    with pytest.raises(RuntimeError, match='closed'):
        monitor.unchanged()


def test_kernel_poll_failure_invalidates_and_releases_the_queue(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    monitor = RevisionMonitor(SourceRevision.capture(tmp_path, '.'))
    real = monitor._queue
    if real is None:
        monitor.close()
        return
    class FailedQueue:
        def control(self, *args):
            raise OSError('kernel poll failed')
        def close(self):
            real.close()
    monitor._queue = FailedQueue()
    assert not monitor.unchanged()
    assert real.closed
    assert monitor.backend == 'metadata'
    assert not monitor.unchanged()
    monitor.close()


@pytest.mark.parametrize('hardlinked', [False, True])
def test_intermediate_alias_retargeting_changes_canonical_scope(tmp_path, hardlinked):
    for name in ['one', 'two', 'middle', 'deep']:
        (tmp_path / name).mkdir()
    one, two = tmp_path / 'one/a.py', tmp_path / 'two/a.py'
    one.write_text('class Worker: pass\n')
    if hardlinked:
        os.link(one, two)
    else:
        two.write_text('class Worker: pass\n')
    middle = tmp_path / 'middle/ref'
    middle.symlink_to(one)
    (tmp_path / 'deep/alias').symlink_to(middle)
    query = QUERY.replace('select $c.name;', 'select $c.path;')
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(query, path='deep/alias')['rows'] == [['one/a.py']]
        middle.unlink()
        middle.symlink_to(two)
        result = host.search(query, path='deep/alias')
        assert result['complete'] is True
        assert result['rows'] == [['two/a.py']]
