"""Walk a project tree honouring `.gitignore` (+ `.ken`, `.git`, etc.).

`pathspec` parses gitignore-format patterns. We accumulate every
`.gitignore` we encounter and apply them to descendants in scope —
matches git's compositional behaviour without shelling out to git
(which would also work but adds a fork per project).

Returned paths are *relative* to the supplied project root, with
forward slashes, mirroring how the DB stores `ci_files.path`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from pathspec import GitIgnoreSpec


# Ken-specific extra ignores. Git already ignores these for most users
# but we shouldn't depend on that — also, `.ken/` itself contains the
# database we're writing to and must never be indexed.
ALWAYS_IGNORE = (
    ".ken/",
    ".git/",
    ".hg/",
    ".svn/",
    ".claude/",        # claude code's local workspace state
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "node_modules/",
    "target/",
    "dist/",
    "build/",
    ".DS_Store",
)


def _read_gitignore(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _make_spec(patterns: Iterable[str]) -> GitIgnoreSpec:
    return GitIgnoreSpec.from_lines(list(patterns))


def iter_files(project_root: Path) -> Iterator[Path]:
    """Yield every file under *project_root* not ignored by gitignore.

    Composes the project's root `.gitignore` (if any) with the static
    `ALWAYS_IGNORE` set. We don't recurse into a directory that's
    itself ignored, which is the only way to avoid traversing
    `.venv/` and `node_modules/` on real-world projects (those can
    contain millions of files).
    """
    root = project_root.resolve()
    spec = _make_spec(ALWAYS_IGNORE)

    root_gi = root / ".gitignore"
    if root_gi.is_file():
        spec = _make_spec([*ALWAYS_IGNORE, *_read_gitignore(root_gi)])

    stack: list[Path] = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = sorted(cur.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                rel = entry.relative_to(root)
            except ValueError:
                continue
            rel_posix = rel.as_posix()
            is_dir = entry.is_dir()
            # gitignore semantics: directory matches need a trailing slash.
            test = rel_posix + "/" if is_dir else rel_posix
            if spec.match_file(test):
                continue
            if is_dir:
                stack.append(entry)
            elif entry.is_file():
                yield rel
