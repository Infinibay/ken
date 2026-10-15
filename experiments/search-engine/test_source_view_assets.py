"""Prepared view scopes are declared by the corpus, with legacy16 compatibility."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from contextual_run import registered_context_spec
from source_view_assets import load_source_views, sha
from ken.retrieval.contextual import OwnerVectorSnapshot
from ken.retrieval.model import EntityKey
from ken.retrieval.source_views import SOURCE_VIEW_PROJECTION


def assets(tmp_path: Path, count: int, *, declared: bool = True) -> dict:
    original = {
        'model_id': 'test/cpu', 'upstream_revision': 'abc',
        'artifacts': {'onnx/model.onnx': 'a'*64, 'tokenizer.json': 'b'*64},
        'query_prefix': 'query: ', 'document_projection': 'full-owner', 'root': '/unused',
    }
    original['spec'] = asdict(registered_context_spec(original))
    model = dict(original, document_projection=SOURCE_VIEW_PROJECTION)
    model['spec'] = asdict(registered_context_spec(model))
    paths = {name: tmp_path/name for name in (
        'source.db', 'vectors.npy', 'registration.json', 'model.json', 'original.json', 'full.db')}
    paths['model.json'].write_text(json.dumps(model))
    paths['original.json'].write_text(json.dumps(original))
    paths['full.db'].write_bytes(b'full-context-fixture')
    owner = EntityKey('owner.py', 'function', 'compute')
    db = sqlite3.connect(paths['source.db'])
    db.execute('CREATE TABLE owners(entity TEXT,source_hash TEXT,view TEXT,vector_index INT)')
    for index, name in enumerate(('contract', 'implementation')):
        db.execute('INSERT INTO owners VALUES (?,?,?,?)',
                   (json.dumps({'path': owner.path, **owner.to_dict()}), 'source-hash', name, index))
    db.commit()
    db.close()
    np.save(paths['vectors.npy'], np.eye(2, dtype=np.float32))
    repositories = [f'repo{i:02}' for i in range(count)]
    metadata = {'source_db_sha256': sha(paths['source.db']),
        'vectors_sha256': sha(paths['vectors.npy']), 'base_full_context_sha256': sha(paths['full.db']),
        'source_generation': 7, 'owners': 1}
    prepared = {'model_registration_sha256': sha(paths['model.json']),
        'original_model_registration_sha256': sha(paths['original.json']),
        'projection': SOURCE_VIEW_PROJECTION,
        'source_repos': {name: metadata for name in repositories}}
    if declared:
        prepared['repositories'] = repositories
    paths['registration.json'].write_text(json.dumps(prepared))
    from ken.retrieval.profile import EncoderSpec

    return {'index': paths['source.db'], 'vectors': paths['vectors.npy'],
        'registration': paths['registration.json'], 'model_registration': paths['model.json'],
        'repo': repositories[0], 'source': OwnerVectorSnapshot(
            EncoderSpec(**original['spec']), 7, (owner,), ('source-hash',), np.array([[1., 0.]])),
        'original_registration': paths['original.json'], 'full_context_index': paths['full.db']}


@pytest.mark.parametrize('count', [1, 16, 63])
def test_live_adapter_accepts_the_complete_declared_repository_scope(tmp_path, count):
    arguments = assets(tmp_path, count)
    result, receipts = load_source_views(**arguments)
    assert result.owners == arguments['source'].owners
    assert result.rows['implementation'].tolist() == [1]
    assert not result.matrix.flags.writeable
    assert str(arguments['registration']) in receipts


def test_legacy16_registration_still_loads_without_new_fields(tmp_path):
    result, _ = load_source_views(**assets(tmp_path, 16, declared=False))
    assert len(result.owners) == 1


@pytest.mark.parametrize('change', ['missing', 'extra', 'duplicate', 'empty', 'string', 'null', 'nonstring'])
@pytest.mark.parametrize('count', [16, 63])
def test_incomplete_or_malformed_declared_scope_fails_before_using_vectors(tmp_path, change, count):
    arguments = assets(tmp_path, count)
    path = arguments['registration']
    prepared = json.loads(path.read_text())
    if change == 'missing':
        del prepared['source_repos'][f'repo{count-1:02}']
    elif change == 'extra':
        prepared['source_repos']['extra'] = prepared['source_repos']['repo00']
    elif change == 'duplicate':
        prepared['repositories'].append('repo00')
    else:
        prepared['repositories'] = {'empty': [], 'string': 'repo00', 'null': None,
                                    'nonstring': [1]}[change]
    path.write_text(json.dumps(prepared))
    with pytest.raises(ValueError, match='registration|scope'):
        load_source_views(**arguments)


def test_legacy_registration_does_not_silently_allow_partial_or_new_corpus(tmp_path):
    with pytest.raises(ValueError, match='registration|scope'):
        load_source_views(**assets(tmp_path, 63, declared=False))
