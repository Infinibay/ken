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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ScopedSpec:
    base: Path
    spec: GitIgnoreSpec


class GitignoreMatcher:
    """Gitignore matcher that composes root and nested `.gitignore` files."""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root.resolve()
        self._always_spec = _make_spec(ALWAYS_IGNORE)
        self._specs: dict[Path, GitIgnoreSpec] = {
            Path("."): _make_spec(_read_gitignore(self.root / ".gitignore")),
        }

    def is_ignored(self, rel: Path, *, is_dir: bool = False) -> bool:
        """Return whether *rel* is ignored by applicable gitignore rules."""
        rel = Path(rel)
        always_path = rel.as_posix() + "/" if is_dir else rel.as_posix()
        if self._always_spec.match_file(always_path):
            return True
        ignored: bool | None = None
        for scoped in self._applicable_specs(rel):
            try:
                local_rel = rel if scoped.base == Path(".") else rel.relative_to(scoped.base)
            except ValueError:
                continue
            local = local_rel.as_posix() + "/" if is_dir else local_rel.as_posix()
            result = scoped.spec.check_file(local)
            if result.include is not None:
                ignored = bool(result.include)
        return bool(ignored)

    def _applicable_specs(self, rel: Path) -> list[_ScopedSpec]:
        specs: list[_ScopedSpec] = []
        parent = rel.parent
        for base in _ancestor_dirs(parent):
            specs.append(_ScopedSpec(base, self._spec_for(base)))
        return specs

    def _spec_for(self, rel_dir: Path) -> GitIgnoreSpec:
        rel_dir = Path(".") if rel_dir == Path("") else rel_dir
        spec = self._specs.get(rel_dir)
        if spec is not None:
            return spec
        gi = self.root / rel_dir / ".gitignore"
        if gi.is_file():
            spec = _make_spec(_read_gitignore(gi))
        else:
            spec = _make_spec(())
        self._specs[rel_dir] = spec
        return spec


def _ancestor_dirs(rel_dir: Path) -> Iterator[Path]:
    yield Path(".")
    if rel_dir == Path("."):
        return
    cur = Path(".")
    for part in rel_dir.parts:
        cur = cur / part
        yield cur


def iter_files(project_root: Path) -> Iterator[Path]:
    """Yield every file under *project_root* not ignored by gitignore.

    Composes nested `.gitignore` files with the static `ALWAYS_IGNORE`
    set. We don't recurse into a directory that's
    itself ignored, which is the only way to avoid traversing
    `.venv/` and `node_modules/` on real-world projects (those can
    contain millions of files).
    """
    root = project_root.resolve()
    matcher = GitignoreMatcher(root)

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
            if matcher.is_ignored(Path(rel_posix), is_dir=is_dir):
                continue
            if is_dir:
                stack.append(entry)
            elif entry.is_file():
                yield rel
