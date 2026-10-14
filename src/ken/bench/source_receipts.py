"""Verify frozen engine bytes, rather than trusting a manifest's own checksum."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def verify_frozen_source(root: Path) -> str:
    root = root.resolve()
    payload = (root / "SOURCE-MANIFEST.json").read_bytes()
    receipt = json.loads(payload)
    files = receipt["files"]
    for name in files:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not (root / name).resolve().is_relative_to(root):
            raise ValueError("frozen manifest path escapes source root")
    inventory = set()
    for name in ("src", "experiments/search-engine", "pyproject.toml"):
        path = root / name
        for item in path.rglob("*") if path.is_dir() else (path,):
            if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                inventory.add(item.relative_to(root).as_posix())
    if inventory != files.keys():
        raise ValueError("frozen source inventory changed")
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(files)}
    if actual != files:
        raise ValueError("frozen source bytes changed")
    if hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest() != receipt["tree_sha256"]:
        raise ValueError("frozen source tree digest does not match inventory")
    return hashlib.sha256(payload).hexdigest()
