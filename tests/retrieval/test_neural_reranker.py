"""Real ONNX scores verify the public CPU reranker boundary without model mocks."""
import hashlib
import json

import numpy as np
import pytest
from onnx import TensorProto as T, helper as h, numpy_helper as nh, save
from tokenizers import Tokenizer, models, pre_tokenizers, processors


@pytest.fixture
def registered_reranker(tmp_path):
    vocab={'[UNK]':0,'x':1,'y':2,**{f'u{i}':i for i in range(3,7)},'[PAD]':7,'[CLS]':8,'[SEP]':9}
    tokenizer=Tokenizer(models.WordLevel(vocab,unk_token='[UNK]'))
    tokenizer.pre_tokenizer=pre_tokenizers.Whitespace()
    tokenizer.post_processor=processors.TemplateProcessing(single='[CLS] $A [SEP]',pair='[CLS] $A [SEP] $B [SEP]',special_tokens=[('[CLS]',8),('[SEP]',9)])
    tokenizer.save(str(tmp_path/'tokenizer.json'))
    (tmp_path/'config.json').write_text(json.dumps({'pad_token_id':7}))
    (tmp_path/'tokenizer_config.json').write_text(json.dumps({'pad_token':'[PAD]','padding_side':'right'}))
    graph=h.make_graph([
        h.make_node('Cast',['input_ids'],['ids'],to=T.FLOAT),
        h.make_node('Cast',['attention_mask'],['mask'],to=T.FLOAT),
        h.make_node('Mul',['ids','mask'],['masked']),
        h.make_node('ReduceSum',['masked','axis'],['scores'],keepdims=1)],'pair_score',
        [h.make_tensor_value_info(n,T.INT64,[1,None]) for n in ('input_ids','attention_mask')],
        [h.make_tensor_value_info('scores',T.FLOAT,[1,1])],
        [nh.from_array(np.array([1],dtype=np.int64),name='axis')])
    save(h.make_model(graph,opset_imports=[h.make_opsetid('',18)],ir_version=9),tmp_path/'graph.onnx')
    sha=lambda n:hashlib.sha256((tmp_path/n).read_bytes()).hexdigest()
    return {'graph':str(tmp_path/'graph.onnx'),'graph_sha256':sha('graph.onnx'),
        'tokenizer':str(tmp_path/'tokenizer.json'),'tokenizer_sha256':sha('tokenizer.json'),
        'upstream':{'root':str(tmp_path),'artifacts':{n:{'sha256':sha(n)} for n in ('config.json','tokenizer_config.json')}}}


def test_real_scores_keep_pair_order_with_default_batch1_cpu_budget(registered_reranker):
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    runtime=ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker))
    scores,details=runtime.score('x',['y','x x x','x','y y'])
    assert scores==[29.,30.,28.,31.]
    assert details['pair_tokens']==[5,7,5,6]
    assert details['pad_id']==7
    assert runtime.providers==('CPUExecutionProvider',)


def test_empty_pool_never_prepares_or_loads_a_model():
    from ken.retrieval.neural_reranker import ONNXReranker
    def unavailable():raise AssertionError('empty pool cannot require assets')
    scores,details=ONNXReranker(unavailable).score('x',[])
    assert scores==[] and details['pair_tokens']==[]
    assert details['inference_ms']==0


def test_document_truncation_stays_within512_and_preserves_query(registered_reranker):
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    runtime=ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker),max_tokens=512)
    scores,details=runtime.score('x',['x '*1000])
    assert scores==[535.]
    assert details['pair_tokens']==[512]
    assert details['truncated_documents']==1
    with pytest.raises(ValueError,match='query.*long|shorten'):
        runtime.score('x '*1000,['y'])


def test_changed_published_padding_fails_before_inference(registered_reranker):
    from pathlib import Path
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    (Path(registered_reranker['upstream']['root'])/'config.json').write_text('{"pad_token_id":0}')
    with pytest.raises(ValueError,match='artifact'):
        ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker)).score('x',['y'])


@pytest.mark.parametrize('value',[0,-1,1.5,True])
def test_invalid_thread_budget_cannot_use_all_cores(value):
    from ken.retrieval.neural_reranker import ONNXReranker
    with pytest.raises(ValueError,match='thread'):
        ONNXReranker(lambda:None,intra_op_threads=value)


def test_native_top10_bound_is_checked_before_model_preparation():
    from ken.retrieval.neural_reranker import ONNXReranker
    def unavailable():raise AssertionError('out-of-contract pool must fail before loading')
    with pytest.raises(ValueError,match='top10'):
        ONNXReranker(unavailable).score('x',['y']*11)


def test_changed_but_validly_pinned_padding_must_match_tokenizer(registered_reranker):
    from pathlib import Path
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    path=Path(registered_reranker['upstream']['root'])/'config.json'
    path.write_text('{"pad_token_id":0}')
    registered_reranker['upstream']['artifacts']['config.json']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='padding'):
        ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker)).score('x',['y'])


def test_model_must_return_one_score_per_document(registered_reranker):
    from pathlib import Path
    import onnx
    from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
    path=Path(registered_reranker['graph']);model=onnx.load(path)
    model.graph.node.append(h.make_node('Concat',['scores','scores'],['two_scores'],axis=1))
    del model.graph.output[:]
    model.graph.output.append(h.make_tensor_value_info('two_scores',T.FLOAT,[1,2]))
    save(model,path);registered_reranker['graph_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='one finite score'):
        ONNXReranker(lambda:RerankerAssets.from_registration(registered_reranker)).score('x',['y'])


def test_default_budget_keeps_a_document_larger_than512_complete(registered_reranker):
    from ken.retrieval.neural_reranker import ONNXReranker, RerankerAssets
    runtime = ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker))
    scores, details = runtime.score('x', ['x ' * 1000])
    assert scores == [1027.]
    assert details['pair_tokens'] == [1004]
    assert details['truncated_documents'] == 0


def test_custom_budget_controls_both_document_and_query_capacity(registered_reranker):
    from ken.retrieval.neural_reranker import ONNXReranker, RerankerAssets
    runtime = ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker), max_tokens=2048)
    scores, details = runtime.score('x', ['x ' * 2000])
    assert scores == [2027.] and details['pair_tokens'] == [2004]
    scores, details = runtime.score('x ' * 2000, ['y'])
    assert scores == [2028.] and details['pair_tokens'] == [2004]
    with pytest.raises(ValueError, match='query.*long|shorten'):
        runtime.score('x ' * 2048, ['y'])


@pytest.mark.parametrize('value', [0, -1, 1.5, True])
def test_invalid_token_budget_fails_without_preparing_assets(value):
    from ken.retrieval.neural_reranker import ONNXReranker
    def unavailable():
        raise AssertionError('invalid budget cannot prepare assets')
    with pytest.raises(ValueError, match='token budget'):
        ONNXReranker(unavailable, max_tokens=value)


@pytest.mark.parametrize('filename,field', [('config.json', 'max_position_embeddings'),
                                           ('tokenizer_config.json', 'model_max_length')])
def test_declared_model_limit_cannot_be_exceeded(registered_reranker, filename, field):
    from pathlib import Path
    from ken.retrieval.neural_reranker import ONNXReranker, RerankerAssets
    path = Path(registered_reranker['upstream']['root']) / filename
    config = json.loads(path.read_text())
    config[field] = 768
    path.write_text(json.dumps(config))
    registered_reranker['upstream']['artifacts'][filename]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='token budget.*model|model.*limit'):
        ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker)).score('x', ['y'])


def test_default_factory_forwards_budget_validation_before_asset_resolution():
    from ken.retrieval.neural_assets import default_reranker
    with pytest.raises(ValueError, match='token budget'):
        default_reranker(max_tokens=True)
