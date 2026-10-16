"""A pinned derivation uses real files and rejects unverified cache publication."""
import hashlib
from pathlib import Path
import shutil

import pytest


@pytest.fixture
def translation_files(tmp_path):
    root = tmp_path / ('a' * 40); root.mkdir()
    files = {'model.bin': b'weights', 'source.spm': b'source', 'target.spm': b'target',
             'config.json': b'{"bos_token":"<s>","x":false}',
             'shared_vocabulary.json': '["<unk>","rojo","á"]'.encode()}
    expected = files | {'config.json': b'{\n  "bos_token": "<s>",\n  "x": false\n}\n',
                        'shared_vocabulary.json': b'[\n  "<unk>",\n  "rojo",\n  "\\u00e1"\n]'}
    for name, data in files.items(): (root / name).write_bytes(data)
    def record(revision, artifacts):
        return {'model_id': 'test/translation', 'revision': revision, 'artifacts': {
            name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            for name, data in artifacts.items()}}
    definition = {'source': record(root.name, files), 'derived': record('b' * 40, expected)}
    return root, definition, expected


def test_preparation_reproduces_measured_json_bytes_and_reuses_verified_cache(translation_files, tmp_path):
    from ken.retrieval.translation_preparation import prepare_translation
    root, definition, expected = translation_files
    dest = tmp_path / 'derived' / ('b' * 40)
    prepare_translation(definition, dest, source_snapshot=root)
    assert {p.name: p.read_bytes() for p in dest.iterdir()} == expected
    shutil.rmtree(root)
    prepare_translation(definition, dest, source_snapshot=root)
    assert (dest / 'model.bin').read_bytes() == b'weights'


def test_failed_derivation_never_publishes_a_partial_model(translation_files, tmp_path):
    from ken.retrieval.translation_preparation import prepare_translation
    root, definition, _ = translation_files
    definition['derived']['artifacts']['config.json']['sha256'] = 'c' * 64
    dest = tmp_path / 'derived' / ('b' * 40)
    with pytest.raises(ValueError, match='artifact'):
        prepare_translation(definition, dest, source_snapshot=root)
    assert not dest.exists()


def test_default_expansion_is_lazy_for_an_english_request(tmp_path):
    from ken.retrieval.translation_preparation import default_query_expansion
    cache = tmp_path / 'no-assets-yet'
    expand = default_query_expansion(cache_root=cache, local_files_only=True)
    assert expand('find the input parser') == 'find the input parser'
    assert not cache.exists()
