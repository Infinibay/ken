import numpy as np
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from ken.bench.pair_relevance import PairRelevance


def tokenizer():
    vocab = {'[UNK]':0, '[CLS]':1, '[SEP]':2, '[PAD]':3, 'query':4, 'good':5, 'other':6}
    t = Tokenizer(models.WordLevel(vocab, unk_token='[UNK]'))
    t.pre_tokenizer = pre_tokenizers.Whitespace()
    t.post_processor = processors.TemplateProcessing(single='[CLS] $A [SEP]',
        pair='[CLS] $A [SEP] $B:1 [SEP]:1', special_tokens=[('[CLS]',1),('[SEP]',2)])
    t.enable_padding(pad_id=3,pad_token='[PAD]')
    return t


class Session:
    def get_inputs(self):
        from types import SimpleNamespace
        return [SimpleNamespace(name='input_ids'), SimpleNamespace(name='attention_mask')]
    def run(self, outputs, inputs):
        assert set(inputs) == {'input_ids','attention_mask'}
        assert inputs['input_ids'].dtype == np.int64
        assert (inputs['input_ids'][:, :3] == [1,4,2]).all()
        assert inputs['input_ids'].shape[1] <= 8
        return [np.any(inputs['input_ids']==5, axis=1).astype(np.float32)[:,None]]


def test_pairs_keep_query_and_separate_document_truncation_in_each_batch():
    judge = PairRelevance(Session(), tokenizer(), max_tokens=8, batch_size=2)
    assert judge.score('query',['good other','other '*20,'good'], purpose='implementation') == [1.,0.,1.]
    assert judge.score('query',[],purpose='implementation') == []
