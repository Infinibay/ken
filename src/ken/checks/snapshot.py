"""Track source membership and contents, including additions and deletions."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import time
from typing import Any

from ken.gitignore_filter import GitignoreMatcher
from ken.knowledge.dependencies import Fingerprints
from .model import digest, relative


def engine_version() -> str:
    from ken.kql2.catalog import sources
    from ken.kql2.service import frontend_fingerprint

    package = Path(__file__).parent.parent
    implementation = [
        (p.relative_to(package).as_posix(), sha256(p.read_bytes()).hexdigest())
        for directory in ("checks", "inspection", "kql2", "structural_store")
        for p in sorted((package / directory).rglob("*.py"))
    ]
    return digest(
        [
            "checks/1",
            frontend_fingerprint(),
            implementation,
            [text for _, text in sources()],
        ]
    )


def capture(root: Path, scope: str, *, seconds: float = 2.0) -> dict[str, Any]:
    from ken.structural.frontend import LANGUAGES

    root = root.resolve()
    scope = relative(scope)
    fingerprints = Fingerprints(
        root, max_files=4000, max_bytes=128_000_000, max_entries=30000, seconds=seconds
    )
    target = fingerprints.path(scope)
    extensions = set(LANGUAGES) | {".c", ".h", ".kt", ".swift", ".scala", ".dart"}
    matcher = GitignoreMatcher(root)
    files: list[Path] = []
    started = time.monotonic()
    entries = 0

    def fail(error: OSError) -> None:
        raise error

    if target.is_file():
        files = [target]
    elif target.is_dir():
        for directory, dirs, names in os.walk(target, followlinks=False, onerror=fail):
            if time.monotonic() - started > seconds:
                raise ValueError("source inventory budget exhausted")
            base = Path(directory)
            dirs[:] = [
                d
                for d in dirs
                if not matcher.is_ignored((base / d).relative_to(root), is_dir=True)
            ]
            if any((base / d).is_symlink() for d in dirs):
                raise ValueError("symlink directory makes source coverage unknown")
            entries += len(dirs) + len(names)
            if entries > 30000:
                raise ValueError("source inventory exceeds 30000 entries")
            files.extend(
                base / name
                for name in names
                if not matcher.is_ignored((base / name).relative_to(root), is_dir=False)
            )
    else:
        raise ValueError("rule scope is missing")
    manifest = []
    for file in sorted(files):
        if file.suffix.lower() in extensions:
            item = fingerprints.snapshot({"path": file.relative_to(root).as_posix()})
            manifest.append([item["path"], item["sha256"]])
    return {"scope": scope, "sha256": digest(manifest), "manifest": manifest}
