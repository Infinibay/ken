"""Prepare generation-bound contextual source views from a reusable vector cache."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any
from collections.abc import Iterable

import numpy as np

from ken.embedder.contextual_onnx import ContextEncoder
from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot
from ken.retrieval.description import OwnerDescription, describe_owner
from ken.retrieval.model import EntityKey
from ken.retrieval.piece_catalog import SourceCatalog, entity_id
from ken.retrieval.profile import EncoderSpec
from ken.retrieval.source_views import SOURCE_VIEW_NAMES, SOURCE_VIEW_PROJECTION, SourceViewSnapshot, owner_view_texts


def _sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _valid(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32)
    if (value.shape != (768,) or not np.isfinite(value).all()
            or not np.isclose(np.linalg.norm(value), 1., rtol=1e-5, atol=1e-5)):
        raise ValueError('context cache requires a normalized finite vector')
    return value


def full_owner_text(description: OwnerDescription) -> str:
    fields = description.fields
    return '\n'.join([description.entity.path, fields['identity'], fields['signature'],
        'Documentation: '+fields['documentation'][:800], 'Source:', fields['implementation']])


class ContextVectorCache:
    """Persist normalized source vectors by exact text and immutable model policy."""
    def __init__(self, directory: Path, model: EncoderSpec):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.directory/'vectors.db', timeout=60)
        self.model = model.key
        self.conn.execute('CREATE TABLE IF NOT EXISTS vectors('
            'model TEXT, hash TEXT, text TEXT, vector BLOB, PRIMARY KEY(model,hash))')

    def __enter__(self) -> ContextVectorCache:
        return self

    def __exit__(self, *args: Any) -> None:
        self.conn.close()

    def get(self, text: str) -> np.ndarray | None:
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self.conn.execute('SELECT text,vector FROM vectors WHERE model=? AND hash=?',
                                (self.model, digest)).fetchone()
        if row is None:
            return None
        if row[0] != text:
            raise ValueError('context cache text identity mismatch')
        return _valid(np.frombuffer(row[1], dtype=np.float32))

    def put(self, text: str, vector: np.ndarray) -> None:
        self.put_many(((text, vector),))

    def put_many(self, items: Iterable[tuple[str, np.ndarray]]) -> None:
        """Import authenticated source-only cache entries in one transaction."""
        def rows():
            for text, vector in items:
                value = _valid(vector)
                yield (self.model, hashlib.sha256(text.encode()).hexdigest(), text, value.tobytes())
        with self.conn:
            self.conn.executemany('INSERT OR IGNORE INTO vectors VALUES (?,?,?,?)', rows())

    def count(self) -> int:
        return int(self.conn.execute('SELECT COUNT(*) FROM vectors WHERE model=?', (self.model,)).fetchone()[0])


def prepare_context(catalog: SourceCatalog, generation: int, encoder: ContextEncoder,
                    directory: Path) -> ContextualRetriever:
    """Reuse exact source projections or encode newly changed ones on CPU.

    Immutable snapshot files are published together after all vectors are ready.
    Generation comes from the caller's pinned source transaction. Cache entries
    never identify an owner by repository name or a query/expected answer.
    """
    # Match canonical SQLite contextual owner ordering, including Unicode escapes.
    owners = tuple(sorted(catalog.owners, key=lambda key: json.dumps(
        {'path': key.path, **key.to_dict()}, sort_keys=True, separators=(',', ':'))))
    if not owners:
        raise ValueError('cannot prepare contextual search without source owners')
    hashes = tuple(catalog.hashes[key.path] for key in owners)
    view_model = replace(encoder.model, document_projection=SOURCE_VIEW_PROJECTION).spec
    texts: list[str] = []
    lookup: dict[str, int] = {}
    indexes: dict[str, list[int]] = {name: [] for name in ('full', *SOURCE_VIEW_NAMES)}
    for key in owners:
        description = describe_owner(catalog.owners[key])
        for name, text in {'full': full_owner_text(description), **owner_view_texts(description)}.items():
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest not in lookup:
                lookup[digest] = len(texts)
                texts.append(text)
            elif texts[lookup[digest]] != text:
                raise ValueError('context source hash collision')
            indexes[name].append(lookup[digest])
    identity = {'schema': 1, 'model': encoder.spec.key, 'view_model': view_model.key,
        'owners': [json.loads(entity_id(key)) for key in owners], 'source_hashes': hashes,
        'texts': list(lookup), 'indexes': indexes}
    encoded = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
    snapshot_key = hashlib.sha256(encoded).hexdigest()
    destination = Path(directory)/'snapshots'/snapshot_key
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='prepare-', dir=destination.parent))
        try:
            # One deduplicated vector pool, then a contiguous full-owner matrix.
            pool = np.lib.format.open_memmap(temporary/'views.npy', mode='w+', dtype=np.float32,
                                            shape=(len(texts), 768))
            with ContextVectorCache(directory, encoder.spec) as cache:
                for i, text in enumerate(texts):
                    value = cache.get(text)
                    if value is None:
                        raw = np.asarray(encoder.embed_passages([text])[0], dtype=np.float32)
                        norm = np.linalg.norm(raw)
                        if not np.isfinite(norm) or norm <= 1e-9:
                            raise ValueError('invalid contextual source norm')
                        value = _valid((raw/norm).astype(np.float32))
                        cache.put(text, value)
                    pool[i] = value
            pool.flush()
            np.save(temporary/'full.npy', pool[indexes['full']], allow_pickle=False)
            del pool
            manifest = {'identity_sha256': snapshot_key, 'artifacts': {
                name: _sha(temporary/name) for name in ('full.npy', 'views.npy')}}
            (temporary/'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
            try:
                temporary.rename(destination)
            except FileExistsError:
                pass  # Another process published the same immutable source key.
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    manifest = json.loads((destination/'manifest.json').read_text())
    if manifest.get('identity_sha256') != snapshot_key or set(manifest.get('artifacts', {})) != {'full.npy','views.npy'}:
        raise ValueError('context artifact manifest mismatch')
    for name, digest in manifest['artifacts'].items():
        if _sha(destination/name) != digest:
            raise ValueError('context artifact hash mismatch; remove this snapshot and prepare again')
    full = OwnerVectorSnapshot(encoder.spec, generation, owners, hashes,
                              np.load(destination/'full.npy', mmap_mode='r', allow_pickle=False))
    views = SourceViewSnapshot(view_model, generation, owners, hashes,
        np.load(destination/'views.npy', mmap_mode='r', allow_pickle=False),
        {name: np.asarray(indexes[name], dtype=np.int64) for name in SOURCE_VIEW_NAMES}, encoder.spec)
    return ContextualRetriever(encoder, full, source_views=views)
