"""The published CLS/dense/GELU/norm/dense head is part of the actual model."""
import json
import math

import numpy as np
import pytest
import onnxruntime as ort
from onnx import TensorProto as T, helper as h, save
from safetensors.numpy import save_file


@pytest.fixture
def published_head(tmp_path):
    tmp_path = tmp_path / ('a' * 40)
    tmp_path.mkdir()
    for n in ('onnx','1_Pooling','2_Dense','3_LayerNorm','4_Dense'):(tmp_path/n).mkdir()
    configs={'1_Pooling':{'embedding_dimension':3,'pooling_mode':'cls'},
        '2_Dense':{'in_features':3,'out_features':3,'bias':False,'activation_function':'torch.nn.modules.activation.GELU'},
        '3_LayerNorm':{'dimension':3},
        '4_Dense':{'in_features':3,'out_features':1,'bias':True,'activation_function':'torch.nn.modules.linear.Identity'}}
    for name,config in configs.items():(tmp_path/name/'config.json').write_text(json.dumps(config))
    save_file({'linear.weight':np.eye(3,dtype=np.float32)},tmp_path/'2_Dense/model.safetensors')
    save_file({'norm.weight':np.ones(3,dtype=np.float32),'norm.bias':np.zeros(3,dtype=np.float32)},tmp_path/'3_LayerNorm/model.safetensors')
    save_file({'linear.weight':np.array([[1.,-2.,.5]],dtype=np.float32),'linear.bias':np.array([.25],dtype=np.float32)},tmp_path/'4_Dense/model.safetensors')
    graph=h.make_graph([], 'backbone_probe',
        [h.make_tensor_value_info(n,T.INT64,[1,None]) for n in ('input_ids','attention_mask')],
        [h.make_tensor_value_info('tokens',T.FLOAT,[1,1,3])],
        [h.make_tensor('tokens',T.FLOAT,[1,1,3],[2.,1.,-1.])])
    save(h.make_model(graph,opset_imports=[h.make_opsetid('',18)],ir_version=9),tmp_path/'onnx/model.onnx')
    return tmp_path


def test_head_assembly_applies_every_published_layer_with_raw_logits(published_head):
    from ken.retrieval.neural_assets import append_published_head
    output=published_head/'complete.onnx'
    append_published_head(published_head,output)
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(output),sess_options=options,providers=['CPUExecutionProvider'])
    actual=float(session.run(None,{'input_ids':np.array([[1]],np.int64),'attention_mask':np.array([[1]],np.int64)})[0][0,0])
    # Independent scalar definition; three dimensions distinguish exactGELU
    # from ReLU without amplifying two-value LayerNorm cancellation error.
    values=[x*.5*(1+math.erf(x/math.sqrt(2))) for x in (2.,1.,-1.)]
    mean=sum(values)/3
    variance=sum((x-mean)**2 for x in values)/3
    normalized=[(x-mean)/math.sqrt(variance+1e-5) for x in values]
    expected=sum(x*w for x,w in zip(normalized,(1.,-2.,.5),strict=True))+.25
    assert abs(actual-expected)<4e-6


def test_unsupported_head_is_rejected_without_publishing_graph(published_head):
    from ken.retrieval.neural_assets import append_published_head
    p=published_head/'2_Dense/config.json';config=json.loads(p.read_text());config['activation_function']='unsupported';p.write_text(json.dumps(config))
    output=published_head/'complete.onnx'
    with pytest.raises(ValueError,match='architecture|head'):
        append_published_head(published_head,output)
    assert not output.exists()


@pytest.fixture
def registered_head(published_head, tmp_path):
    import hashlib
    from tokenizers import Tokenizer,models,pre_tokenizers
    from ken.retrieval.neural_assets import append_published_head
    root=published_head
    tokenizer=Tokenizer(models.WordLevel({'[UNK]':0,'x':1,'[PAD]':2},unk_token='[UNK]'))
    tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    tokenizer.save(str(root/'tokenizer.json'))
    (root/'config.json').write_text('{"pad_token_id":2}')
    (root/'tokenizer_config.json').write_text('{"pad_token":"[PAD]","padding_side":"right"}')
    # The separate test above verifies the compiler's arithmetic. Here its valid
    # output supplies the fixture pin for testing cache publication and reuse.
    graph=tmp_path/'reference.onnx';append_published_head(root,graph)
    record={'model_id':'test/reranker','revision':root.name,'artifacts':{
        p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in root.rglob('*') if p.is_file()}}
    return root,{'source':record,'graph':{'path':'model.onnx','bytes':graph.stat().st_size,'sha256':hashlib.sha256(graph.read_bytes()).hexdigest()}}


def test_prepared_reranker_is_verified_and_reused_without_upstream(registered_head,tmp_path):
    import shutil
    from ken.retrieval.neural_assets import prepare_reranker
    root,definition=registered_head
    destination=tmp_path/'ready'
    assets=prepare_reranker(definition,destination,source_snapshot=root)
    assets.verify()
    assert (destination/'config.json').read_text()=='{"pad_token_id":2}'
    shutil.rmtree(root)
    again=prepare_reranker(definition,destination,source_snapshot=root)
    assert again==assets
    (destination/'model.onnx').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='artifact'):
        prepare_reranker(definition,destination,source_snapshot=root)


def test_failed_graph_derivation_does_not_publish_partial_cache(registered_head,tmp_path):
    from ken.retrieval.neural_assets import prepare_reranker
    root,definition=registered_head;definition['graph']['sha256']='b'*64
    destination=tmp_path/'ready'
    with pytest.raises(ValueError,match='artifact'):
        prepare_reranker(definition,destination,source_snapshot=root)
    assert not destination.exists()
