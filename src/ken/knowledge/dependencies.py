"""Bounded, read-only fingerprints of the inputs a finding depends on.

A tree tracks membership as well as content. This matters for negative search
results: a new file can change the answer without modifying any old evidence.
Fingerprints establish equality of declared inputs, never truth or completeness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import time
from typing import Any


class Unavailable(ValueError):
    """An input cannot be checked within the declared scope and budget."""


@dataclass
class Fingerprints:
    root: Path
    max_files: int = 256
    max_bytes: int = 16 * 1024 * 1024
    max_entries: int = 10000
    seconds: float = 0.2
    _files: int = 0
    _bytes: int = 0
    _entries: int = 0
    _started: float = field(default_factory=time.monotonic)
    _cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # macOS temporary roots commonly arrive through /var -> /private/var.
        # Resolve the workspace once; only links *inside* it are dependencies.
        self.root = self.root.resolve()

    def _check_time(self) -> None:
        if time.monotonic() - self._started > self.seconds:
            raise Unavailable("dependency check budget exhausted")

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("dependency path must be nonempty")
        if ".." in Path(value).parts:
            raise ValueError("dependency paths cannot traverse parent directories")
        candidate = self.root / value
        root = self.root.resolve()
        try:
            candidate.resolve().relative_to(root)
            # Do not silently change a recorded path into its symlink target.
            relative = candidate.absolute().relative_to(root)
        except ValueError as exc:
            raise ValueError("dependencies must stay inside the project") from exc
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise Unavailable("symlink dependencies are not supported")
        return candidate.resolve()

    def snapshot(self, spec: dict[str, Any]) -> dict[str, str]:
        if not isinstance(spec, dict) or set(spec) - {
            "kind",
            "path",
            "pattern",
            "sha256",
        }:
            raise ValueError("dependency fields: kind, path, pattern, sha256")
        kind = spec.get("kind", "file")
        if not isinstance(kind, str) or kind not in {"file", "tree"}:
            raise ValueError("dependency kind must be file or tree")
        path = self.path(spec.get("path", ""))
        clean = {"kind": kind, "path": path.relative_to(self.root.resolve()).as_posix()}
        if kind == "tree":
            pattern = spec.get("pattern", "*")
            if not isinstance(pattern, str) or not pattern or len(pattern) > 256:
                raise ValueError("tree pattern must contain 1..256 characters")
            clean["pattern"] = pattern
        elif "pattern" in spec:
            raise ValueError("pattern only applies to tree dependencies")
        key = json.dumps(clean, sort_keys=True)
        if key not in self._cache:
            self._check_time()
            self._cache[key] = (
                self._tree(path, clean["pattern"])
                if kind == "tree"
                else self._file(path)
            )
        return clean | {"sha256": self._cache[key]}

    def _file(self, path: Path) -> str:
        self._check_time()
        if self._files >= self.max_files:
            raise Unavailable("dependency file budget exhausted")
        self._files += 1
        if not path.is_file() or path.is_symlink():
            raise Unavailable("dependency file missing or unsupported")
        # Read a bounded number of bytes even if the file grows after stat().
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            data = stream.read(max(0, self.max_bytes - self._bytes) + 1)
            after = os.fstat(stream.fileno())
        self._bytes += len(data)
        if self._bytes > self.max_bytes:
            raise Unavailable("dependency byte budget exhausted")
        current = path.stat()
        stamps = {
            (s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            for s in (before, after, current)
        }
        if len(stamps) != 1:
            raise Unavailable("dependency changed during inspection")
        self._check_time()
        return sha256(data).hexdigest()

    def _tree(self, path: Path, pattern: str) -> str:
        if not path.is_dir():
            raise Unavailable("dependency directory missing")
        entries: list[tuple[str, str]] = []
        directories: list[tuple[Path, int]] = []

        def fail(error: OSError) -> None:
            raise error

        for directory, dirs, files in os.walk(path, onerror=fail, followlinks=False):
            self._check_time()
            base = Path(directory)
            directories.append((base, base.stat().st_mtime_ns))
            self._entries += len(dirs) + len(files)
            if self._entries > self.max_entries:
                raise Unavailable("dependency tree budget exhausted")
            if any((base / name).is_symlink() for name in dirs):
                raise Unavailable("symlink directories make tree coverage unknown")
            for name in sorted(files):
                file = base / name
                relative = file.relative_to(path).as_posix()
                if PurePosixPath(relative).match(pattern):
                    entries.append((relative, self._file(file)))
        if any(
            directory.stat().st_mtime_ns != stamp for directory, stamp in directories
        ):
            raise Unavailable("dependency tree changed during inspection")
        return sha256(json.dumps(sorted(entries)).encode()).hexdigest()


def capture(specs: list[dict[str, Any]], root: Path) -> list[dict[str, str]]:
    fingerprints = Fingerprints(root, seconds=2.0)
    snapshots: dict[str, dict[str, str]] = {}
    for spec in specs:
        snapshot = fingerprints.snapshot(spec)
        expected = spec.get("sha256")
        if expected is not None and expected != snapshot["sha256"]:
            raise ValueError(f"dependency changed before recording: {snapshot['path']}")
        key = json.dumps(
            {k: v for k, v in snapshot.items() if k != "sha256"}, sort_keys=True
        )
        snapshots[key] = snapshot
    return list(snapshots.values())


def assess(
    dependencies: list[dict[str, Any]], fingerprints: Fingerprints | None
) -> dict[str, Any]:
    if (
        not isinstance(dependencies, list)
        or len(dependencies) > 48
        or any(not isinstance(d, dict) for d in dependencies)
    ):
        return {"state": "unknown", "issues": ["invalid dependency declarations"]}
    if not dependencies:
        return {"state": "untracked", "issues": ["no declared dependencies"]}
    if fingerprints is None:
        return {"state": "unknown", "issues": ["project root unavailable"]}
    changed, unavailable = [], []
    for spec in dependencies:
        try:
            current = fingerprints.snapshot(spec)
            if current["sha256"] != spec["sha256"]:
                changed.append(spec["path"])
        except (OSError, ValueError) as exc:
            unavailable.append(f"{spec.get('path', '?')}: {exc}")
    return {
        "state": "stale" if changed else "unknown" if unavailable else "unchanged",
        "issues": changed + unavailable,
        "scope": "declared dependencies only; not a truth or coverage check",
    }
