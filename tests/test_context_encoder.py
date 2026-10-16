"""A real ONNX graph exposes prefix, truncation and unnormalized output policy."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from onnx import TensorProto, helper, save
from tokenizers import Tokenizer, models, pre_tokenizers


@pytest.fixture
def contextual_model(tmp_path):
    root = tmp_path / ('b' * 40)
    (root / 'onnx').mkdir(parents=True)
    t = Tokenizer(models.WordLevel({'[UNK]': 0, 'find': 1, 'red': 2, '[PAD]': 3}, unk_token='[UNK]'))
    t.pre_tokenizer = pre_tokenizers.Whitespace()
    t.enable_padding(pad_id=3, pad_token='[PAD]')
    t.save(str(root / 'tokenizer.json'))
    nodes = [helper.make_node('ReduceSum', ['input_ids', 'axes'], ['ids'], keepdims=1),
             helper.make_node('ReduceSum', ['attention_mask', 'axes'], ['mask'], keepdims=1),
             helper.make_node('Cast', ['ids'], ['x'], to=TensorProto.FLOAT),
             helper.make_node('Cast', ['mask'], ['y'], to=TensorProto.FLOAT),
             helper.make_node('Concat', ['x', 'y', 'zeros'], ['sentence_embedding'], axis=1)]
    initializers = [helper.make_tensor('axes', TensorProto.INT64, [1], [1]),
                    helper.make_tensor('zeros', TensorProto.FLOAT, [1, 766], [0.] * 766)]
    graph = helper.make_graph(nodes, 'raw-vector-probe', [
        helper.make_tensor_value_info(n, TensorProto.INT64, [1, 'tokens'])
        for n in ('input_ids', 'attention_mask')], [
        helper.make_tensor_value_info('sentence_embedding', TensorProto.FLOAT, [1, 768])], initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 18)], ir_version=10)
    save(model, root / 'onnx/model.onnx')
    record = {'model_id': 'test/context', 'revision': root.name, 'artifacts': {
        name: {'bytes': (root / name).stat().st_size, 'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()}
        for name in ('onnx/model.onnx', 'tokenizer.json')}}
    return root, record


def test_real_context_graph_preserves_raw_output_prefix_and_batch1_policy(contextual_model):
    from ken.embedder.contextual_onnx import ContextModel, ContextEncoder
    from ken.model_assets import ModelAssets
    root, record = contextual_model
    definition = ContextModel(ModelAssets.from_dict(record), 'find ', 'test-source-projection')
    encoder = ContextEncoder(definition, snapshot=root)
    query = encoder.embed_query('red')
    passage = encoder.embed_passages(['red'])[0]
    np.testing.assert_array_equal(query[:2], [3., 2.])
    np.testing.assert_array_equal(passage[:2], [2., 1.])
    assert query.shape == (768,)
    assert np.count_nonzero(query[2:]) == 0
    assert encoder.providers == ('CPUExecutionProvider',)
    assert encoder.spec == definition.spec
    assert encoder.embed_passages([]) == []


def test_context_encoder_caps_tokens_at512_without_padding_into_vectors(contextual_model):
    from ken.embedder.contextual_onnx import ContextModel, ContextEncoder
    from ken.model_assets import ModelAssets
    root, record = contextual_model
    encoder = ContextEncoder(ContextModel(ModelAssets.from_dict(record), 'find ', 'projection'), snapshot=root)
    np.testing.assert_array_equal(encoder.embed_passages(['red ' * 1000])[0][:2], [1024., 512.])
    np.testing.assert_array_equal(encoder.embed_passages(['red', 'red red'])[0][:2], [2., 1.])


def test_context_asset_corruption_is_rejected_before_session_creation(contextual_model):
    from ken.embedder.contextual_onnx import ContextModel, ContextEncoder
    from ken.model_assets import ModelAssets
    root, record = contextual_model
    (root / 'onnx/model.onnx').write_bytes(b'invalid graph')
    encoder = ContextEncoder(ContextModel(ModelAssets.from_dict(record), 'find ', 'projection'), snapshot=root)
    with pytest.raises(ValueError, match='artifact'):
        encoder.embed_query('red')


def test_context_model_identity_includes_projection_and_query_prefix(contextual_model):
    from ken.embedder.contextual_onnx import ContextModel
    from ken.model_assets import ModelAssets
    _, record = contextual_model
    assets = ModelAssets.from_dict(record)
    a = ContextModel(assets, 'find ', 'projection')
    b = ContextModel(assets, 'search ', 'projection')
    c = ContextModel(assets, 'find ', 'other-projection')
    assert len({a.spec, b.spec, c.spec}) == 3
