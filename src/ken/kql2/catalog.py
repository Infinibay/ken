"""Explicit packaged KQL 2 library snapshot, without importing catalog execution."""
from __future__ import annotations

from importlib.resources import files
from functools import lru_cache
from hashlib import sha256
import tomllib
import re
from collections.abc import Mapping

from .syntax import File, parse
from .cache import ArtifactCache
from .graph import FrozenQuery, freeze, relational_plan

_COMPILED: ArtifactCache[FrozenQuery] = ArtifactCache(8_000_000)


def sources() -> tuple[tuple[str, str], ...]:
    return tuple((str(path), path.read_text(encoding='utf-8'))
                 for directory in ('patterns', 'modern_patterns')
                 for path in sorted(files('ken.structural').joinpath(directory).iterdir(), key=lambda p: p.name)
                 if path.name.endswith('.toml'))


@lru_cache(maxsize=1)
def _libraries(snapshot: tuple[tuple[str, str], ...]) -> tuple[tuple[str, File], ...]:
    result = {}
    for path, text in snapshot:
        data = tomllib.loads(text)
        for entry in (data, *data.get('variants', []), *data.get('operations', [])):
            source = entry.get('query', '')
            if source.lstrip().startswith('language "kql/2"'):
                tree = parse(source, str(path))
                if tree.module in result:
                    raise ValueError('duplicate catalog module: ' + tree.module)
                result[tree.module] = tree
    return tuple(result.items())


def libraries() -> dict[str, File]:
    return dict(_libraries(sources()))


@lru_cache(maxsize=1)
def _snapshot_key(snapshot: tuple[tuple[str, str], ...]) -> str:
    return sha256(repr(snapshot).encode()).hexdigest()


def _compile(source: str, snapshot: tuple[tuple[str, str], ...]):
    from .compiler import compile
    key = sha256((_snapshot_key(snapshot) + source).encode()).hexdigest()
    def compute():
        tree = parse(source)
        available = dict(_libraries(snapshot))
        selected = {}
        pending = list(tree.imports)
        while pending:
            name = pending.pop()
            if name not in selected and name in available:
                selected[name] = available[name]
                pending.extend(available[name].imports)
        program = compile(tree, libraries=selected, relational=True)
        return freeze(relational_plan(program))
    return _COMPILED.get_or_compute(key, compute)[0]


def packaged_libraries() -> dict[str, str]:
    """Capture packaged texts once for an explicit prepared library revision."""
    result = {}
    for _, text in sources():
        data = tomllib.loads(text)
        for entry in (data, *data.get('variants', []), *data.get('operations', [])):
            query = entry.get('query', '')
            if query.lstrip().startswith('language "kql/2"'):
                # Reuse the immutable syntax snapshot instead of parsing 138
                # declarations on every artifact lookup.
                match = re.search(r'(?m)(?:^|;)\s*module\s+([\w.]+);', query)
                if match:
                    result[match[1]] = query
    return result


def with_packaged_libraries(
    source: str,
    supplied=None,
    *,
    packaged: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Include exact packaged texts in the same key as supplied libraries."""
    supplied = dict(supplied or {})
    if 'ken.catalog.' not in source and not any('ken.catalog.' in text for text in supplied.values()):
        return supplied
    return {**(packaged_libraries() if packaged is None else packaged), **supplied}


def compile_source(source: str, *, snapshot: tuple[tuple[str, str], ...] | None = None):
    return _compile(source, sources() if snapshot is None else snapshot)
