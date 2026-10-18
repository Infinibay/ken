"""Resolve query text and reachable imports from one explicit registry snapshot."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .registry import RegisteredModule, RegistryReader, RegistrySnapshot
from .syntax import File, parse


@lru_cache(maxsize=128)
def _tree(source: str) -> File:
    return parse(source)


@dataclass(frozen=True)
class ResolvedQuery:
    source: str
    query_name: str | None
    libraries: Mapping[str, str]
    revisions: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "libraries", MappingProxyType(dict(self.libraries)))
        object.__setattr__(self, "revisions", MappingProxyType(dict(self.revisions)))

    def annotate(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.revisions:
            result.setdefault("analysis", {})["registry_modules"] = dict(self.revisions)
        return result


def validate_entry(source: str | None, saved_query: str | None) -> None:
    if bool(source) == bool(saved_query):
        raise ValueError("provide either query source or saved_query, not both")


def _resolve(source: str | None, saved_query: str | None, query_name: str | None,
             supplied: Mapping[str, str] | None,
             lookup: Callable[[str], RegisteredModule | None],
             packaged: Callable[[], Mapping[str, str]]) -> ResolvedQuery:
    validate_entry(source, saved_query)
    revisions: dict[str, str] = {}
    if saved_query:
        record = lookup(saved_query)
        if record is None:
            raise ValueError("registered KQL2 module not found: " + saved_query)
        if not record.queries:
            raise ValueError("registered module has no executable query: " + saved_query)
        if query_name is not None and query_name not in record.queries:
            raise ValueError("query not declared in registered module: " + query_name)
        source = record.source
        revisions[record.module] = record.revision
    assert source is not None
    libraries = dict(supplied or {})
    if "import" not in source:
        return ResolvedQuery(source, query_name, libraries, revisions)
    entry = _tree(source)
    visited = {entry.module, "ken.core"}
    pending = list(entry.imports)
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        text = libraries.get(name)
        if text is None and name.startswith("ken.catalog."):
            text = packaged().get(name)
        if text is None:
            record = lookup(name)
            if record is None:
                raise ValueError("missing library module: " + name)
            text = record.source
            revisions[name] = record.revision
        tree = _tree(text)
        if tree.module != name:
            raise ValueError("mismatched library module: " + name)
        libraries[name] = text
        pending.extend(tree.imports)
    return ResolvedQuery(source, query_name, libraries, revisions)


class ModuleResolver:
    """Bind each request's entry and imports, reusing the owner's registry reader."""

    def __init__(self, root: Path):
        self._root = root
        self._reader: RegistryReader | None = None
        self._closed = False
        self._packaged: Mapping[str, str] | None = None

    def _catalog(self) -> Mapping[str, str]:
        if self._packaged is None:
            from .catalog import packaged_libraries

            self._packaged = packaged_libraries()
        return self._packaged

    def resolve(self, source: str | None = None, *, saved_query: str | None = None,
                query_name: str | None = None,
                libraries: Mapping[str, str] | None = None,
                packaged: Mapping[str, str] | None = None) -> ResolvedQuery:
        if self._closed:
            raise RuntimeError("module resolver is closed")
        snapshot: RegistrySnapshot | None = None

        def lookup(name: str) -> RegisteredModule | None:
            nonlocal snapshot
            if snapshot is None:
                if self._reader is None:
                    self._reader = RegistryReader(self._root)
                snapshot = self._reader.snapshot()
            return snapshot.modules.get(name)

        return _resolve(source, saved_query, query_name, libraries, lookup,
                        self._catalog if packaged is None else lambda: packaged)

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        self._closed = True

    def __enter__(self) -> ModuleResolver:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def validate_imports(source: str, modules: Mapping[str, RegisteredModule]) -> None:
    from .catalog import packaged_libraries

    _resolve(source, None, None, None, modules.get, packaged_libraries)
