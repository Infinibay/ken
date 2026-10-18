"""Cheap admission checks for a revision whose bytes were captured beforehand."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import select
import stat
from typing import Any

from ken._paths import resolve_project_path
from ken.gitignore_filter import PROJECT_IGNORE_FILE, iter_entries
from ken.structural.frontend import LANGUAGES

Stamp = tuple[int, int, int, int, int, int] | None


def stamp(path: Path) -> Stamp:
    try:
        state = path.stat()
        return (state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns,
                state.st_ctime_ns, state.st_mode)
    except OSError:
        return None


@dataclass(frozen=True)
class SourceRevision:
    inputs: tuple[tuple[Path, Stamp], ...]
    aliases: tuple[tuple[Path, Path], ...] = ()
    scope_identity: tuple[Path, Path] | None = None

    @classmethod
    def capture(cls, root: Path, path: str) -> SourceRevision:
        target = resolve_project_path(root, path)
        lexical = root / path
        inputs = {target, lexical, root / '.gitignore', root / PROJECT_IGNORE_FILE,
                  root / '.ken/structural.json'}
        for directory in {*target.parents, *lexical.parents}:
            if directory == root or directory.is_relative_to(root):
                inputs.add(directory)
                inputs.add(directory / '.gitignore')
        if target.is_dir():
            inputs.add(target / '.gitignore')
            for relative, is_dir in iter_entries(root, path=path):
                if is_dir:
                    inputs.add(root / relative / '.gitignore')
                if is_dir or relative.suffix.lower() in LANGUAGES or relative.name == '.gitignore':
                    inputs.add(root / relative)
        aliases = tuple((file, file.resolve()) for file in sorted(inputs) if file.is_symlink())
        scoped = any(file == lexical or file in lexical.parents for file, _ in aliases)
        return cls(tuple((file, stamp(file)) for file in sorted(inputs)), aliases,
                   (lexical, target) if scoped else None)

    def aliases_unchanged(self) -> bool:
        try:
            return (all(path.resolve() == target for path, target in self.aliases)
                    and (self.scope_identity is None
                         or self.scope_identity[0].resolve() == self.scope_identity[1]))
        except (OSError, RuntimeError):
            return False

    def unchanged(self) -> bool:
        return self.aliases_unchanged() and all(stamp(file) == expected for file, expected in self.inputs)


class RevisionMonitor:
    """Validate a captured revision through kernel events or metadata checks.

    Vnode events remain in the kernel queue until polled, including edits before
    the asynchronous watcher's debounce. Every input and missing input's parent
    is watched. Registration verifies the captured metadata before adoption.
    """

    def __init__(self, revision: SourceRevision):
        self.revision = revision
        self._queue: Any = None
        self._fds: list[int] = []
        self._parent_fds: set[int] = set()
        self._dirty = False
        self._closed = False
        factory = getattr(select, 'kqueue', None)
        if factory is None:
            return
        try:
            self._queue = factory()
            paths = dict(revision.inputs)
            input_paths = set(paths)
            for path, expected in revision.inputs:
                if expected is None or not stat.S_ISDIR(expected[-1]) or path.is_symlink():
                    parent = path.parent
                    while (state := stamp(parent)) is None and parent != parent.parent:
                        parent = parent.parent
                    paths.setdefault(parent, state)
            changes = []
            flags = sum(getattr(select, name) for name in (
                'KQ_NOTE_WRITE', 'KQ_NOTE_DELETE', 'KQ_NOTE_RENAME', 'KQ_NOTE_ATTRIB',
                'KQ_NOTE_EXTEND', 'KQ_NOTE_LINK', 'KQ_NOTE_REVOKE'))
            for path, expected in paths.items():
                if expected is None:
                    continue
                fd = os.open(path, getattr(os, 'O_EVTONLY', os.O_RDONLY) | os.O_NONBLOCK)
                self._fds.append(fd)
                if path not in input_paths:
                    self._parent_fds.add(fd)
                descriptor_state = os.fstat(fd)
                actual = (descriptor_state.st_dev, descriptor_state.st_ino, descriptor_state.st_size,
                          descriptor_state.st_mtime_ns, descriptor_state.st_ctime_ns, descriptor_state.st_mode)
                self._dirty |= actual != expected
                changes.append(getattr(select, 'kevent')(fd,
                    filter=getattr(select, 'KQ_FILTER_VNODE'),
                    flags=getattr(select, 'KQ_EV_ADD') | getattr(select, 'KQ_EV_CLEAR'),
                    fflags=flags))
            self._queue.control(changes, 0, 0)
            self._dirty |= not revision.unchanged()
        except (OSError, AttributeError):
            # Unsupported descriptors or a low fd limit may never produce a
            # partially monitored success: release everything and check metadata.
            self.close()
            self._closed = False
            self._dirty = False
        except BaseException:
            self.close()
            raise

    @property
    def backend(self) -> str:
        return 'kernel_vnode' if self._queue is not None else 'metadata'

    def unchanged(self) -> bool:
        if self._closed:
            raise RuntimeError('revision monitor is closed')
        if self._queue is None:
            self._dirty |= not self.revision.unchanged()
            return not self._dirty
        self._dirty |= not self.revision.aliases_unchanged()
        try:
            events = self._queue.control([], 1, 0)
            if events:
                # A parent watched only for an absent configuration also sees
                # unrelated Ken DB/WAL files. Verify the declared inputs before
                # treating that event as a source edit. Direct input events stay
                # conservative, including replacements and restored timestamps.
                self._dirty |= (any(event.ident not in self._parent_fds for event in events)
                                or not self.revision.unchanged())
        except (OSError, ValueError):
            self.close()
            self._closed = False
            self._dirty = True
        return not self._dirty

    def close(self) -> None:
        self._closed = True
        errors = []
        if self._queue is not None:
            try:
                self._queue.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._queue = None
        for fd in list(self._fds):
            try:
                os.close(fd)
            except BaseException as exc:
                errors.append(exc)
            else:
                self._fds.remove(fd)
                self._parent_fds.discard(fd)
        if errors:
            raise errors[0]
