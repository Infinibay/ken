import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ken.bench.static_embeddings import StaticEmbeddingControl


@pytest.fixture(autouse=True)
def isolated_optional_runtime(monkeypatch):
    monkeypatch.setattr('ken.bench.static_embeddings.version', lambda name: 'test-version')


def fixture(tmp_path):
    root = tmp_path / ('a' * 40)
    root.mkdir()
    files = {'model.safetensors': b'weights', 'tokenizer.json': b'tokenizer', 'config.json': b'{}'}
    for name, data in files.items():
        (root / name).write_bytes(data)
    record = {'model_id': 'test/static', 'revision': root.name, 'artifacts': {
        name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        for name, data in files.items()}}
    calls = []
    def load(path, **kwargs):
        calls.append((path, kwargs))
        return SimpleNamespace(embedding=np.zeros((5, 2), dtype=np.float32),
            tokenizer=SimpleNamespace(no_padding=lambda: None, no_truncation=lambda: None),
            tokenize=lambda texts, max_length: [[1] * len(texts[0].split())],
            encode=lambda texts, **kw: np.array([[.6, .8] for _ in texts], dtype=np.float32))
    return root, record, load, calls


def test_registered_control_is_offline_normalized_and_has_full_token_counts(tmp_path):
    root, record, load, calls = fixture(tmp_path)
    control = StaticEmbeddingControl(root, record, loader=load)
    assert calls == [(root, {'normalize': True, 'force_download': False})]
    assert control.token_count('token ' * 1000) == 1000
    assert control.spec.backend == 'provided'
    assert control.spec.model_id == 'test/static'
    assert len(control.spec.revision) == 64
    assert control.embed_passages([]) == []
    np.testing.assert_allclose(control.embed_query('query'), [.6, .8])


def test_control_checks_tokenizer_and_revision_before_loading(tmp_path):
    root, record, load, calls = fixture(tmp_path)
    (root / 'tokenizer.json').write_bytes(b'TOKENIZER')
    with pytest.raises(ValueError, match='artifact'):
        StaticEmbeddingControl(root, record, loader=load)
    assert not calls
    with pytest.raises(ValueError, match='revision'):
        StaticEmbeddingControl(tmp_path, record, loader=load)


def test_profile_identity_changes_with_registered_projection_inputs(tmp_path):
    root, record, load, _ = fixture(tmp_path)
    first = StaticEmbeddingControl(root, record, loader=load)
    data = b'new tokenizer'
    (root / 'tokenizer.json').write_bytes(data)
    record['artifacts']['tokenizer.json'] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    second = StaticEmbeddingControl(root, record, loader=load)
    assert first.spec.revision != second.spec.revision
    assert first.identity['artifacts']['tokenizer.json']['sha256'] == hashlib.sha256(b'tokenizer').hexdigest()
    record['artifacts'].pop('model.safetensors')
    with pytest.raises(ValueError, match='weights'):
        StaticEmbeddingControl(root, record, loader=load)


def test_registered_cache_blob_symlinks_work_and_relative_traversal_is_rejected(tmp_path):
    root, record, load, _ = fixture(tmp_path)
    blob = tmp_path / 'blob'
    (root / 'model.safetensors').rename(blob)
    (root / 'model.safetensors').symlink_to(blob)
    assert StaticEmbeddingControl(root, record, loader=load).spec.backend == 'provided'
    record['artifacts']['../blob'] = record['artifacts']['model.safetensors']
    with pytest.raises(ValueError, match='path'):
        StaticEmbeddingControl(root, record, loader=load)


def test_control_clears_batch_padding_and_hidden_truncation_before_encoding(tmp_path):
    root, record, _, _ = fixture(tmp_path)
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0, 'token': 1, 'query': 2, '[PAD]': 3}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.enable_padding(pad_id=3, pad_token='[PAD]')
    tokenizer.enable_truncation(max_length=4)
    table = np.array([[0., 0.], [1., 0.], [0., 1.], [.5, .5]], dtype=np.float32)
    def encode(texts, **kwargs):
        means = [table[e.ids].mean(axis=0) for e in tokenizer.encode_batch(texts, add_special_tokens=False)]
        return np.array([v / np.linalg.norm(v) for v in means])
    native = SimpleNamespace(embedding=table, tokenizer=tokenizer, encode=encode,
        tokenize=lambda texts, max_length: [e.ids for e in tokenizer.encode_batch(texts, add_special_tokens=False)])
    control = StaticEmbeddingControl(root, record, loader=lambda *a, **kw: native)
    assert control.token_count('token ' * 1000) == 1000
    np.testing.assert_array_equal(control.embed_query('query'), control.embed_passages(['query', 'token ' * 20])[0])
    assert control.identity['tokenizer_policy'] == 'no-padding-no-hidden-truncation-v1'
