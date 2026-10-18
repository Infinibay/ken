"""Durable, revisioned KQL2 modules in the project's knowledge database."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from threading import get_ident
import time
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any, Iterator

from ken._paths import resolve_project_path
from ken.db import connect, init_schema

from .syntax import File, parse


@dataclass(frozen=True)
class RegisteredModule:
    module: str
    source: str
    description: str
    revision: str
    queries: tuple[str, ...]
    patterns: tuple[str, ...]
    imports: tuple[str, ...]
    updated_ns: int

    def to_dict(self, *, source: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "module": self.module, "description": self.description,
            "revision": self.revision, "queries": list(self.queries),
            "patterns": list(self.patterns), "imports": list(self.imports),
            "updated_ns": self.updated_ns,
        }
        if source:
            result["source"] = self.source
        return result


def module_tree(source: str) -> File:
    if not isinstance(source, str) or not source or len(source.encode()) > 100_000:
        raise ValueError("a KQL2 module of at most 100000 bytes is required")
    tree = parse(source)
    if tree.module == "ken.core" or tree.module.startswith("ken.catalog."):
        raise ValueError("reserved KQL2 module namespace: " + tree.module)
    if not any(d.kind in {"query", "pattern"} for d in tree.declarations):
        raise ValueError("a registered module must declare a query or pattern")
    names = [d.name for d in tree.declarations]
    if len(names) != len(set(names)):
        raise ValueError("duplicate module declaration")
    return tree


def _record(row: sqlite3.Row) -> RegisteredModule:
    exports = json.loads(row["exports"])
    return RegisteredModule(
        row["module"], row["source"], row["description"], row["revision"],
        tuple(exports["queries"]), tuple(exports["patterns"]),
        tuple(json.loads(row["imports"])), row["updated_ns"],
    )


class ModuleRegistry:
    """Author modules without retaining connections or touching index caches."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("project root does not exist or is not a directory")
        self.path = resolve_project_path(self.root, ".ken/ken.db")

    def list_modules(self) -> list[RegisteredModule]:
        if not self.path.is_file():
            return []
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='kql_modules'").fetchone()
            return [] if exists is None else [
                _record(row) for row in db.execute("SELECT * FROM kql_modules ORDER BY module")
            ]

    def get(self, module: str) -> RegisteredModule:
        for record in self.list_modules():
            if record.module == module:
                return record
        raise ValueError("registered KQL2 module not found: " + module)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(self.path)) as db:
            init_schema(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def save(self, source: str, *, description: str | None = None,
             expected_revision: str | None = None) -> RegisteredModule:
        tree = module_tree(source)
        if description is not None and (not isinstance(description, str) or len(description) > 2000):
            raise ValueError("description must contain at most 2000 characters")
        from .module_inputs import validate_imports

        validate_imports(source, {record.module: record for record in self.list_modules()})
        with self._write() as db:
            row = db.execute("SELECT * FROM kql_modules WHERE module=?", (tree.module,)).fetchone()
            old = _record(row) if row is not None else None
            if expected_revision is not None and (old is None or old.revision != expected_revision):
                raise ValueError("module revision changed; read it before updating")
            description = description if description is not None else old.description if old else ""
            if old is not None and old.source == source and old.description == description:
                return old
            if old is not None and expected_revision is None:
                raise ValueError("module already exists; supply its current expected_revision to update")
            validate_imports(source, {
                row["module"]: _record(row) for row in db.execute("SELECT * FROM kql_modules")
            })
            record = RegisteredModule(
                tree.module, source, description, sha256((source + "\0" + description).encode()).hexdigest(),
                tuple(d.name for d in tree.declarations if d.kind == "query"),
                tuple(d.name for d in tree.declarations if d.kind == "pattern"),
                tuple(tree.imports), time.time_ns(),
            )
            db.execute(
                "INSERT INTO kql_modules VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(module) DO UPDATE SET source=excluded.source, "
                "description=excluded.description,revision=excluded.revision, "
                "exports=excluded.exports,imports=excluded.imports,updated_ns=excluded.updated_ns",
                (record.module, source, description, record.revision,
                 json.dumps({"queries": record.queries, "patterns": record.patterns}),
                 json.dumps(record.imports), record.updated_ns),
            )
            return record

    def delete(self, module: str, *, expected_revision: str | None = None) -> None:
        self.get(module)
        with self._write() as db:
            row = db.execute("SELECT revision FROM kql_modules WHERE module=?", (module,)).fetchone()
            if row is None:
                raise ValueError("registered KQL2 module not found: " + module)
            if expected_revision is not None and row[0] != expected_revision:
                raise ValueError("module revision changed; read it before deleting")
            users = [row["module"] for row in db.execute("SELECT module,imports FROM kql_modules")
                     if row["module"] != module and module in json.loads(row["imports"])]
            if users:
                raise ValueError("module is imported by: " + ", ".join(users))
            db.execute("DELETE FROM kql_modules WHERE module=?", (module,))


@dataclass(frozen=True)
class RegistrySnapshot:
    generation: int
    modules: Mapping[str, RegisteredModule]


class RegistryReader:
    """Own a read connection and immutable snapshots across prepared requests."""

    def __init__(self, root: Path):
        registry = ModuleRegistry(root)
        self.root, self.path = registry.root, registry.path
        self._owner = (os.getpid(), get_ident())
        self._closed = False
        self._db: sqlite3.Connection | None = None
        self._identity: tuple[Path, int, int] | None = None
        self._snapshot = RegistrySnapshot(-1, MappingProxyType({}))

    def snapshot(self) -> RegistrySnapshot:
        if self._closed or self._owner != (os.getpid(), get_ident()):
            raise RuntimeError("registry readers belong to their open owner process and thread")
        path = resolve_project_path(self.root, ".ken/ken.db")
        try:
            stat = path.stat()
            identity = (path, stat.st_dev, stat.st_ino)
        except FileNotFoundError:
            identity = None
        if identity != self._identity:
            if self._db is not None:
                self._db.close()
                self._db = None
            self._identity = None
            self._snapshot = RegistrySnapshot(-1, MappingProxyType({}))
        if identity is None:
            return self._snapshot
        if self._db is None:
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)
            db.row_factory = sqlite3.Row
            self.path = path
            self._db, self._identity = db, identity
        db = self._db
        try:
            row = db.execute("SELECT generation FROM kql_registry_state WHERE singleton=1").fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            self._snapshot = RegistrySnapshot(-1, MappingProxyType({}))
            return self._snapshot
        generation = row[0] if row is not None else 0
        if generation == self._snapshot.generation:
            return self._snapshot
        db.execute("BEGIN")
        try:
            generation = db.execute("SELECT generation FROM kql_registry_state WHERE singleton=1").fetchone()[0]
            records = {row["module"]: _record(row) for row in db.execute("SELECT * FROM kql_modules")}
        finally:
            db.rollback()
        self._snapshot = RegistrySnapshot(generation, MappingProxyType(records))
        return self._snapshot

    def close(self) -> None:
        if self._owner != (os.getpid(), get_ident()):
            raise RuntimeError("registry readers belong to their creating process and thread")
        if self._db is not None:
            self._db.close()
            self._db = None
        self._closed = True
