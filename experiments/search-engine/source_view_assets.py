"""Bind prepared source-view artifacts to the existing live query encoder."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from ken.retrieval.contextual import OwnerVectorSnapshot
from ken.retrieval.model import EntityKey
from ken.retrieval.profile import EncoderSpec
from ken.retrieval.source_views import SOURCE_VIEW_NAMES, SOURCE_VIEW_PROJECTION, SourceViewSnapshot


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_source_views(*, index: Path, vectors: Path, registration: Path,
                      model_registration: Path, repo: str, source: OwnerVectorSnapshot,
                      original_registration: Path, full_context_index: Path
                      ) -> tuple[SourceViewSnapshot, dict[str, str]]:
    from contextual_run import registered_context_spec

    receipts = {str(p): sha(p) for p in (index, vectors, registration, model_registration)}
    prepared = json.loads(registration.read_text())
    model = json.loads(model_registration.read_text())
    original_model = json.loads(original_registration.read_text())
    if (len(prepared['source_repos']) != 16
            or prepared['model_registration_sha256'] != receipts[str(model_registration)]
            or prepared['original_model_registration_sha256'] != sha(original_registration)
            or EncoderSpec(**original_model['spec']) != source.model):
        raise ValueError('incomplete or changed source view model registration')
    if (model['document_projection'] != SOURCE_VIEW_PROJECTION
            or prepared['projection'] != SOURCE_VIEW_PROJECTION
            or EncoderSpec(**model['spec']) != registered_context_spec(model)):
        raise ValueError('source view projection registration differs from its runtime')
    for name in ('root', 'artifacts', 'query_prefix', 'model_id', 'upstream_revision'):
        if model[name] != original_model[name]:
            raise ValueError('source views must reuse the identical registered query encoder')
    metadata = prepared['source_repos'][repo]
    if (metadata['source_db_sha256'] != receipts[str(index)]
            or metadata['vectors_sha256'] != receipts[str(vectors)]
            or metadata['base_full_context_sha256'] != sha(full_context_index)
            or str(metadata['source_generation']) != str(source.generation)
            or metadata['owners'] != len(source.owners)):
        raise ValueError('source view artifacts differ from their complete source snapshot')
    db = sqlite3.connect(f'file:{index}?mode=ro', uri=True)
    try:
        encoded = db.execute('SELECT entity,source_hash,view,vector_index FROM owners').fetchall()
    finally:
        db.close()
    entries = {(EntityKey(**json.loads(e)), name): (digest, row)
               for e, digest, name, row in encoded}
    expected = {(owner, name) for owner in source.owners for name in SOURCE_VIEW_NAMES}
    if len(encoded) != len(expected) or set(entries) != expected:
        raise ValueError('source view rows must cover every complete source owner exactly once')
    for owner, digest in zip(source.owners, source.source_hashes, strict=True):
        if any(entries[(owner, name)][0] != digest for name in SOURCE_VIEW_NAMES):
            raise ValueError('source view owner source changed')
    rows = {name: np.array([entries[(owner, name)][1] for owner in source.owners])
            for name in SOURCE_VIEW_NAMES}
    snapshot = SourceViewSnapshot(EncoderSpec(**model['spec']), source.generation,
        source.owners, source.source_hashes, np.load(vectors, mmap_mode='r'), rows,
        query_model=source.model)
    return snapshot, receipts
