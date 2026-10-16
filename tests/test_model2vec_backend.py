"""Real tiny static models exercise Ken's pooling and pinned-asset boundary."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from model2vec import StaticModel
from tokenizers import Tokenizer, models, pre_tokenizers


@pytest.fixture
def registered_model(tmp_path):
    snapshot = tmp_path / ('a' * 40)
    tok = Tokenizer(models.WordLevel({'[UNK]': 0, 'red': 1, 'blue': 2, '[PAD]': 3}, unk_token='[UNK]'))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.enable_padding(pad_id=3, pad_token='[PAD]')
    tok.enable_truncation(max_length=2)
    StaticModel(np.array([[0., 0.], [1., 0.], [0., 1.], [100., 100.]], dtype=np.float32),
                tok, normalize=True).save_pretrained(snapshot)
    record = {'model_id': 'test/static', 'revision': snapshot.name, 'license': 'mit',
              'artifacts': {name: {'bytes': (snapshot / name).stat().st_size,
                  'sha256': hashlib.sha256((snapshot / name).read_bytes()).hexdigest()}
                  for name in ('config.json', 'model.safetensors', 'modules.json', 'tokenizer.json')}}
    return snapshot, record


def test_real_native_pooling_is_normalized_and_independent_of_batch_padding(registered_model):
    from ken.embedder.model2vec_backend import RegisteredStaticEncoder
    snapshot, record = registered_model
    encoder = RegisteredStaticEncoder(snapshot, record)
    actual = encoder.embed_passages(['red', 'red blue', 'red red blue', '', 'unknown'])
    np.testing.assert_allclose(actual, [[1., 0.], [2 ** -.5, 2 ** -.5],
                                      [2 / 5 ** .5, 1 / 5 ** .5], [0., 0.], [0., 0.]], atol=1e-7)
    np.testing.assert_array_equal(encoder.embed_query('red'), actual[0])
    np.testing.assert_array_equal(encoder.embed_queries(['red', 'blue']), [[1., 0.], [0., 1.]])
    assert encoder.dim == 2
    assert encoder.token_count('red ' * 1000) == 1000
    assert encoder.embed_passages([]) == []
    assert encoder.identity['tokenizer_policy'] == 'no-padding-no-hidden-truncation-v1'


def test_weights_and_tokenizer_must_match_before_native_loading(registered_model):
    from ken.embedder.model2vec_backend import RegisteredStaticEncoder
    snapshot, record = registered_model
    tokenizer = snapshot / 'tokenizer.json'
    tokenizer.write_text(tokenizer.read_text() + ' ')
    with pytest.raises(ValueError, match='artifact'):
        RegisteredStaticEncoder(snapshot, record)


def test_lazy_public_backend_uses_an_offline_pinned_hub_snapshot(registered_model, tmp_path):
    from ken.model_assets import ModelAssets
    from ken.embedder.model2vec_backend import Model2VecEmbedder
    snapshot, record = registered_model
    assets = ModelAssets.from_dict(record)
    cache = tmp_path / 'hub'
    root = cache / 'models--test--static' / 'snapshots' / snapshot.name
    root.mkdir(parents=True)
    for name in record['artifacts']:
        (root / name).write_bytes((snapshot / name).read_bytes())
    encoder = Model2VecEmbedder(assets, cache_dir=cache, local_files_only=True)
    np.testing.assert_array_equal(encoder.embed_query('red'), [1., 0.])
    np.testing.assert_array_equal(encoder.embed_queries(['red', 'blue']), [[1., 0.], [0., 1.]])
    assert encoder.dim == 2
    # A cached corrupt file must not trigger a network fallback or run unchecked.
    (root / 'model.safetensors').write_bytes(b'bad')
    with pytest.raises(ValueError, match='artifact'):
        Model2VecEmbedder(assets, cache_dir=cache, local_files_only=True).embed_query('red')


def test_missing_offline_assets_fail_with_preparation_instructions(registered_model, tmp_path):
    from ken.model_assets import ModelAssets, ModelPreparationError
    from ken.embedder.model2vec_backend import Model2VecEmbedder
    _, record = registered_model
    backend = Model2VecEmbedder(ModelAssets.from_dict(record), cache_dir=tmp_path / 'empty', local_files_only=True)
    with pytest.raises(ModelPreparationError, match='prepare|download'):
        backend.embed_query('red')


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'a/../../outside', 'a\\outside'])
def test_asset_manifest_rejects_unsafe_paths(registered_model, name):
    from ken.model_assets import ModelAssets
    _, record = registered_model
    record['artifacts'][name] = {'bytes': 1, 'sha256': 'b' * 64}
    with pytest.raises(ValueError, match='path'):
        ModelAssets.from_dict(record)


def test_asset_manifest_is_immutable_and_roundtrips_without_machine_paths(registered_model):
    from ken.model_assets import ModelAssets
    _, record = registered_model
    assets = ModelAssets.from_dict(record)
    before = assets.fingerprint
    record['artifacts']['config.json']['sha256'] = 'b' * 64
    assert assets.fingerprint == before
    assert ModelAssets.from_dict(json.loads(json.dumps(assets.to_dict()))) == assets
    assert 'root' not in assets.to_dict()


def test_registered_potion_routes_to_static_backend_without_network_or_torch():
    from ken.embedder import _build_backend, is_static_model
    from ken.embedder.model2vec_backend import Model2VecEmbedder
    backend = _build_backend('minishlab/potion-code-16M-v2')
    assert isinstance(backend, Model2VecEmbedder)
    assert is_static_model('minishlab/potion-code-16M-v2')


def test_potion_profile_roundtrip_pins_runtime_and_refuses_changed_assets():
    from dataclasses import replace
    from ken.retrieval.profile import RetrievalProfile, load_encoder, potion_profile
    from ken.embedder.model2vec_backend import Model2VecEmbedder
    profile = potion_profile()
    assert profile.identity == profile.behavior
    assert profile.behavior.backend == 'model2vec'
    assert profile.behavior.dtype == 'float16'
    assert profile.behavior.sequence_length == 512
    assert RetrievalProfile.from_dict(profile.to_dict()) == profile
    assert isinstance(load_encoder(profile.behavior), Model2VecEmbedder)
    with pytest.raises(ValueError, match='registered|pinned'):
        load_encoder(replace(profile.behavior, revision='b' * 64))
    with pytest.raises(ValueError, match='registered|pinned'):
        load_encoder(replace(profile.behavior, sequence_length=256))


def test_native_runtime_does_not_load_transformer_packages(registered_model):
    import os
    import subprocess
    snapshot, record = registered_model
    script = '''
import json, sys
from pathlib import Path
from ken.embedder.model2vec_backend import RegisteredStaticEncoder
encoder = RegisteredStaticEncoder(Path(sys.argv[1]), json.loads(sys.argv[2]))
print(json.dumps({'vector': encoder.embed_query('red').tolist(),
    'heavy': sorted(set(sys.modules) & {'torch', 'transformers', 'sentence_transformers'})}))
'''
    result = subprocess.run([sys.executable, '-c', script, str(snapshot), json.dumps(record)],
        env=os.environ | {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {'vector': [1., 0.], 'heavy': []}


def test_same_size_weight_corruption_is_rejected_before_encoding(registered_model):
    from ken.embedder.model2vec_backend import RegisteredStaticEncoder
    snapshot, record = registered_model
    weights = snapshot / 'model.safetensors'
    data = bytearray(weights.read_bytes())
    data[-1] ^= 1
    weights.write_bytes(data)
    with pytest.raises(ValueError, match='artifact'):
        RegisteredStaticEncoder(snapshot, record)
