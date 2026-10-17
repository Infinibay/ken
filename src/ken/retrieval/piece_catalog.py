"""Canonical source owners, physical lines and lexical piece containment."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ken.retrieval.model import EntityKey, Passage, Span, merge_spans

CALLABLE_KINDS = frozenset({'function', 'method', 'constructor', 'destructor'})
SYMBOL_KINDS = CALLABLE_KINDS | {'const', 'constant'}


def entity_id(key: EntityKey) -> str:
    return json.dumps({'path': key.path, **key.to_dict()}, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def module_name(path: str) -> str | None:
    p = Path(path)
    if p.suffix not in {'.py','.pyi','.js','.jsx','.mjs','.cjs','.ts','.tsx','.mts','.cts'}:
        return None
    if any(part.startswith('.') or part in {'node_modules', 'vendor'} for part in p.parts[:-1]):
        return None
    parts = list(p.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    if parts and parts[0] == 'src':
        parts.pop(0)
    if p.suffix in {'.py','.pyi'} and not all(x.isidentifier() for x in parts):
        return None
    return '.'.join(parts) if p.suffix in {'.py','.pyi'} else '/'.join(parts)


class SourceCatalog:
    """Bind owner identity/containment to authenticated current physical source."""

    def __init__(self, root: Path, owners: Mapping[EntityKey, Sequence[Passage]]) -> None:
        self.root = Path(root).resolve()
        self.owners = {key: tuple(passages) for key, passages in owners.items()}
        self._extents: dict[EntityKey, tuple[int, int]] = {}
        self._scopes: dict[EntityKey, tuple[EntityKey, ...] | None] = {}
        self.by_path: dict[str, list[EntityKey]] = defaultdict(list)
        self.lines: dict[str, list[str]] = {}
        self.hashes: dict[str, str] = {}
        for key, passages in self.owners.items():
            if not passages:
                raise ValueError('empty source owner')
            path = (self.root/key.path).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('source outside root')
            if key.path not in self.lines:
                data = path.read_bytes()
                self.lines[key.path] = data.decode('utf-8').splitlines()
                self.hashes[key.path] = hashlib.sha256(data).hexdigest()
            if any(p.source_hash != self.hashes[key.path] for p in passages):
                raise ValueError('stale source catalog: '+key.path)
            self.by_path[key.path].append(key)
        self.classes: dict[EntityKey, EntityKey] = {}
        for keys in self.by_path.values():
            classes = [key for key in keys if key.kind == 'class']
            for key in keys:
                candidates = [outer for outer in classes if self.encloses(outer, key)]
                if candidates:
                    candidates.sort(key=lambda k: (self.extent(k)[1]-self.extent(k)[0], entity_id(k)))
                    if len(candidates) > 1 and self.extent(candidates[0]) == self.extent(candidates[1]):
                        raise ValueError('ambiguous enclosing class')
                    self.classes[key] = candidates[0]

    def extent(self, key: EntityKey) -> tuple[int, int]:
        if key not in self._extents:
            self._extents[key] = (min(p.entity_span.start_line for p in self.owners[key]),
                                  max(p.entity_span.end_line for p in self.owners[key]))
        return self._extents[key]

    def encloses(self, outer: EntityKey, inner: EntityKey) -> bool:
        return bool(outer != inner and outer.path == inner.path and outer.qualname and inner.qualname
            and inner.qualname.startswith(outer.qualname+'.')
            and self.extent(outer)[0] <= self.extent(inner)[0] <= self.extent(inner)[1] <= self.extent(outer)[1])

    def scope_members(self, key: EntityKey) -> tuple[EntityKey, ...] | None:
        """Descendants that account for each nonblank physical line in a scope."""
        if key not in self._scopes:
            descendants = tuple(sorted((k for k in self.by_path[key.path] if self.encloses(key, k)), key=entity_id))
            covered = {line for member in (key, *descendants)
                       for start, end in self.owned_ranges(member) for line in range(start, end+1)}
            start, end = self.extent(key)
            self._scopes[key] = (descendants if all(line in covered or not self.lines[key.path][line-1].strip()
                                for line in range(start, end+1)) else None)
        return self._scopes[key]

    def enclosing_callable(self, key: EntityKey) -> EntityKey | None:
        candidates = [k for k in self.by_path[key.path] if k.kind in CALLABLE_KINDS and self.encloses(k, key)]
        def order(k: EntityKey) -> tuple[int, int]:
            return self.extent(k)[1]-self.extent(k)[0], -len(k.qualname or '')
        candidates.sort(key=lambda k: (order(k), entity_id(k)))
        if not candidates or len(candidates) > 1 and order(candidates[0]) == order(candidates[1]):
            return None
        return candidates[0]

    def owned_ranges(self, key: EntityKey, *, implementation: bool = False) -> list[tuple[int, int]]:
        intervals = []
        for passage in self.owners[key]:
            start = passage.span.start_line
            if implementation and passage.implementation_start_line:
                start = max(start, passage.implementation_start_line)
            if start <= passage.span.end_line:
                intervals.append(Span(start, passage.span.end_line))
        return [(span.start_line, span.end_line) for span in merge_spans(intervals)]

    def source_inventory(self) -> list[dict]:
        return [{'path': k.path, 'entity': k.to_dict(), 'source_hash': self.hashes[k.path],
            'extent': self.extent(k), 'owned_ranges': [[p.span.start_line, p.span.end_line] for p in self.owners[k]],
            'enclosing_class': self.classes[k].to_dict() if k in self.classes else None}
            for k in sorted(self.owners, key=entity_id)]

    def primary(self, key: EntityKey, kind: str) -> EntityKey | str | None:
        if kind == 'class':
            return key if key.kind == 'class' else self.classes.get(key)
        if kind == 'symbol':
            return key if key.kind in SYMBOL_KINDS else None
        if kind == 'module':
            return key.path if module_name(key.path) is not None else None
        if kind == 'file':
            return key.path
        raise ValueError('unknown piece kind')
