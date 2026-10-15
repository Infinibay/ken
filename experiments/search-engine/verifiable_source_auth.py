"""Authenticate attributed evidence without imposing a renderer selection policy.

Literal, correctly attributed helpers may support a primary unit. Whether the
visible call path proves the requested behavior remains the blind judge's task.
The frozen v98 renderer and its stricter selection validator are unchanged.
"""
from __future__ import annotations

import hashlib

from ken.retrieval.model import EntityKey
from verifiable_pieces import MAX_CHARS, MAX_EXCERPTS, MAX_LINES, canonical, module_name


def authenticate_card(card, catalog):
    unit = card['unit']
    path, kind = unit['path'], unit['target_kind']
    if path not in catalog.hashes or card['source_hash'] != catalog.hashes[path]:
        raise ValueError('unknown/stale primary source')
    if kind in {'class', 'symbol'}:
        key = EntityKey(path=path, **unit['entity'])
        if key not in catalog.owners or catalog.primary(key, kind) != key:
            raise ValueError('wrong canonical primary identity')
    elif kind not in {'module', 'file'} or unit['entity'] is not None or (
            kind == 'module' and module_name(path) is None):
        raise ValueError('wrong physical/import unit')
    expected_module = module_name(path) if kind == 'module' else None
    if unit.get('module_name') != expected_module:
        raise ValueError('incorrect module identity metadata')
    paths = {path}
    count = 0
    for excerpt in card['excerpts']:
        ep = excerpt['path']
        start, end = excerpt['start_line'], excerpt['end_line']
        if (ep not in catalog.hashes or excerpt['source_hash'] != catalog.hashes[ep]
                or type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= len(catalog.lines[ep])):
            raise ValueError('invalid excerpt provenance')
        if isinstance(excerpt['entity'], dict):
            owner = EntityKey(path=ep, **excerpt['entity'])
        elif excerpt['entity'] is None and kind in {'module', 'file'}:
            owner = EntityKey(ep, 'module', None)
        else:
            raise ValueError('missing canonical excerpt owner')
        if owner not in catalog.owners:
            raise ValueError('unknown excerpt owner')
        owned = {line for p in catalog.owners[owner]
                 for line in range(p.span.start_line, p.span.end_line + 1)}
        if not set(range(start, end + 1)) <= owned:
            raise ValueError('excerpt crosses source ownership')
        if excerpt['content'] != '\n'.join(catalog.lines[ep][start - 1:end]):
            raise ValueError('fabricated excerpt')
        count += end - start + 1
        paths.add(ep)
    if count > MAX_LINES or len(card['excerpts']) > MAX_EXCERPTS or len(canonical(card)) > MAX_CHARS:
        raise ValueError('card budget exceeded')
    for source_path in paths:
        if hashlib.sha256((catalog.root / source_path).read_bytes()).hexdigest() != catalog.hashes[source_path]:
            raise ValueError('source changed since catalog')
