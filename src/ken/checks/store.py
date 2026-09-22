"""Reviewable rule definitions and immutable receipts, published atomically."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from ken.knowledge.dependencies import Fingerprints
from .model import Rule


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.base = Fingerprints(self.root).path(".ken/checks")

    def path(self, kind: str, key: str) -> Path:
        if kind not in {"rules", "runs"} or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", key
        ):
            raise ValueError("invalid check reference")
        return Fingerprints(self.root).path(f".ken/checks/{kind}/{key}.json")

    def read(self, kind: str, key: str) -> dict[str, Any]:
        path = self.path(kind, key)
        with path.open("rb") as stream:
            data = stream.read(16_000_001)
        if len(data) > 16_000_000:
            raise ValueError("check record exceeds 16 MB")
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported check record")
        return value

    def rules(self) -> list[dict[str, Any]]:
        directory = Fingerprints(self.root).path(".ken/checks/rules")
        if not directory.exists():
            return []
        records = []
        for path in sorted(directory.glob("*.json")):
            record = self.read("rules", path.stem)
            rule = Rule.read(record["definition"])
            if rule.id != path.stem:
                raise ValueError("rule id does not match filename")
            records.append(record)
        return records

    def write(self, kind: str, key: str, value: dict[str, Any]) -> None:
        path = self.path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    @contextmanager
    def lock(self):
        self.base.mkdir(parents=True, exist_ok=True)
        path = Fingerprints(self.root).path(".ken/checks/.lock")
        with path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def save_rule(
        self, record: dict[str, Any], previous: dict[str, Any] | None
    ) -> None:
        rule = Rule.read(record["definition"])
        with self.lock():
            path = self.path("rules", rule.id)
            current = self.read("rules", rule.id) if path.exists() else None
            if current != previous:
                raise ValueError("rule changed concurrently; read it before retrying")
            self.write("rules", rule.id, record)
