"""Assemble the published FP32 reranker head from pinned data without Torch."""
from __future__ import annotations

import json
import math
from importlib import import_module
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from ken.model_assets import ModelArtifact, ModelAssets
from ken.retrieval.neural_reranker import ONNXReranker, RerankerAssets

import numpy as np


def _published_head(root: Path) -> tuple[dict[str, np.ndarray], int]:
    load_file = import_module('safetensors.numpy').load_file
    read = lambda name: json.loads((root/name/'config.json').read_bytes())
    pool, dense, norm, out = (read(name) for name in ('1_Pooling','2_Dense','3_LayerNorm','4_Dense'))
    hidden = pool['embedding_dimension']
    if (type(hidden) is not int or hidden < 1 or pool['pooling_mode'] != 'cls'
            or dense['in_features'] != hidden or dense['out_features'] != hidden or dense['bias']
            or dense['activation_function'] != 'torch.nn.modules.activation.GELU'
            or norm['dimension'] != hidden or out['in_features'] != hidden
            or out['out_features'] != 1 or not out['bias']
            or out['activation_function'] != 'torch.nn.modules.linear.Identity'):
        raise ValueError('unsupported published head architecture')
    d, n, o = (load_file(root/name/'model.safetensors') for name in ('2_Dense','3_LayerNorm','4_Dense'))
    weights = {'dense': d['linear.weight'], 'norm_weight': n['norm.weight'],
        'norm_bias': n['norm.bias'], 'out': o['linear.weight'], 'out_bias': o['linear.bias']}
    expected = {'dense': (hidden,hidden), 'norm_weight': (hidden,),
                'norm_bias': (hidden,), 'out': (1,hidden), 'out_bias': (1,)}
    if any(weights[k].shape != shape or weights[k].dtype != np.float32
           or not np.isfinite(weights[k]).all() for k, shape in expected.items()):
        raise ValueError('unsupported or nonfinite published head weights')
    return weights, hidden


def append_published_head(root: Path, output: Path) -> None:
    """Compile validated module data into CLS/Dense/exactGELU/LayerNorm/Dense."""
    if output.exists():
        raise ValueError('new assembled graph path required')
    weights, _ = _published_head(root)
    onnx = import_module('onnx')
    helper, numpy_helper, tensor = onnx.helper, onnx.numpy_helper, onnx.TensorProto
    model = onnx.load(root/'onnx/model.onnx')
    if len(model.graph.output) != 1 or model.opset_import[0].version != 18:
        raise ValueError('unsupported published backbone output or opset')
    token_output = model.graph.output[0].name
    prefix = 'ken_published_head/'
    def const(name: str, value: Any) -> str:
        full = prefix+name
        model.graph.initializer.append(numpy_helper.from_array(np.asarray(value), full))
        return full
    def node(op: str, inputs: list[str], name: str, **attrs: Any) -> str:
        full = prefix+name
        model.graph.node.append(helper.make_node(op, inputs, [full], name=full, **attrs))
        return full
    cls = node('Gather',[token_output,const('cls_index',np.array(0,np.int64))],'cls',axis=1)
    dense = node('MatMul',[cls,const('dense_weight',weights['dense'].T)],'dense')
    scaled = node('Div',[dense,const('sqrt2',np.array(math.sqrt(2),np.float32))],'scaled')
    gauss = node('Erf',[scaled],'erf')
    added = node('Add',[gauss,const('one',np.array(1,np.float32))],'plus_one')
    product = node('Mul',[dense,added],'gelu_product')
    gelu = node('Mul',[product,const('half',np.array(.5,np.float32))],'gelu')
    norm = node('LayerNormalization',[gelu,const('norm_weight',weights['norm_weight']),
        const('norm_bias',weights['norm_bias'])],'norm',axis=-1,epsilon=1e-5)
    scores = node('MatMul',[norm,const('out_weight',weights['out'].T)],'scores')
    logits = node('Add',[scores,const('out_bias',weights['out_bias'])],'logits')
    del model.graph.output[:]
    model.graph.output.append(helper.make_tensor_value_info(logits,tensor.FLOAT,['batch_size',1]))
    onnx.checker.check_model(model)
    onnx.save(model,output)


def prepare_reranker(definition: Mapping[str, Any], destination: Path, *, source_snapshot: Path | None = None,
                     cache_dir: Path | None = None, local_files_only: bool = False) -> RerankerAssets:
    """Publish only a fully authenticated graph and its tokenizer/padding files."""
    import os
    import shutil
    import tempfile
    source = ModelAssets.from_dict(definition['source'])
    graph = ModelArtifact(**definition['graph'])
    pins = {a.path: a.sha256 for a in source.artifacts}
    def ready(root: Path) -> RerankerAssets:
        return RerankerAssets(root/graph.path, graph.sha256,
            root/'tokenizer.json', pins['tokenizer.json'],
            root/'config.json', pins['config.json'],
            root/'tokenizer_config.json', pins['tokenizer_config.json'])
    if destination.is_dir():
        result = ready(destination)
        result.verify()
        return result
    snapshot = (source.verify(source_snapshot) if source_snapshot is not None else
                source.resolve(cache_dir=cache_dir, local_files_only=local_files_only))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prepare-reranker-', dir=destination.parent) as stage:
        prepared = Path(stage)/'ready'
        prepared.mkdir()
        output = prepared/graph.path
        output.parent.mkdir(parents=True, exist_ok=True)
        append_published_head(snapshot, output)
        for name in ('tokenizer.json','config.json','tokenizer_config.json'):
            shutil.copyfile(snapshot/name, prepared/name)
        ready(prepared).verify()
        try:
            os.rename(prepared, destination)
        except OSError:
            if not destination.is_dir():
                raise
        result = ready(destination)
        result.verify()
        return result


def default_reranker(*, cache_root: Path | None = None, cache_dir: Path | None = None,
                     local_files_only: bool = False) -> ONNXReranker:
    """The measured68M FP32 model, prepared lazily on its first nonempty pool."""
    import hashlib
    import os
    from importlib import resources
    definition = json.loads(resources.files('ken.embedder').joinpath('data/ettin-68m-fp32.json').read_text())
    recipe = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()
    if cache_root is None:
        cache_root = Path(os.environ.get('KEN_CACHE_DIR', str(Path.home()/'.cache'/'ken'))).expanduser()
    root = cache_root/'models'/'ettin'/recipe/definition['source']['revision']
    return ONNXReranker(lambda: prepare_reranker(definition, root,
        cache_dir=cache_dir, local_files_only=local_files_only))
