"""Real ONNX boundary checks for bounded reranker batches and score alignment."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto as T, helper as h, numpy_helper as nh
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from ettin_cpu import CPUReranker


class BoundedBatches(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        vocab = {'[UNK]': 0, 'x': 1, 'y': 2, **{f'unused{i}': i for i in range(3, 7)},
                 '[PAD]': 7, '[CLS]': 8, '[SEP]': 9}
        tokenizer = Tokenizer(models.WordLevel(vocab, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.post_processor = processors.TemplateProcessing(single='[CLS] $A [SEP]',
            pair='[CLS] $A [SEP] $B [SEP]', special_tokens=[('[CLS]', 8), ('[SEP]', 9)])
        tokenizer.save(str(self.root / 'tokenizer.json'))
        (self.root / 'config.json').write_text(json.dumps({'pad_token_id': 7}))
        (self.root / 'tokenizer_config.json').write_text(json.dumps({'pad_token': '[PAD]', 'padding_side': 'right'}))

    def registration(self, batch=None):
        # A one-pair-only graph catches silently ignoring the requested bound.
        graph = h.make_graph([
            h.make_node('Cast', ['input_ids'], ['ids'], to=T.FLOAT),
            h.make_node('Cast', ['attention_mask'], ['mask'], to=T.FLOAT),
            h.make_node('Mul', ['ids', 'mask'], ['masked']),
            h.make_node('ReduceSum', ['masked', 'axis'], ['scores'], keepdims=1)], 'pair_score',
            [h.make_tensor_value_info(n, T.INT64, [batch, None]) for n in ('input_ids', 'attention_mask')],
            [h.make_tensor_value_info('scores', T.FLOAT, [batch, 1])],
            [nh.from_array(np.array([1], dtype=np.int64), name='axis')])
        model = h.make_model(graph, opset_imports=[h.make_opsetid('', 18)], ir_version=9)
        onnx.save(model, self.root / 'graph.onnx')
        sha = lambda name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        return {'graph': str(self.root / 'graph.onnx'), 'graph_sha256': sha('graph.onnx'),
            'tokenizer': str(self.root / 'tokenizer.json'), 'tokenizer_sha256': sha('tokenizer.json'),
            'upstream': {'root': str(self.root), 'artifacts': {n: {'sha256': sha(n)}
                for n in ('config.json', 'tokenizer_config.json')}}}

    def test_one_pair_bound_is_honored_and_scores_keep_document_order(self):
        runtime = CPUReranker(self.registration(batch=1), batch_size=1)
        scores, details = runtime.score('x', ['y', 'x x x', 'x', 'y y'])
        self.assertEqual(scores, [29., 30., 28., 31.])
        self.assertEqual(details['pair_tokens'], [5, 7, 5, 6])

    def test_padding_never_changes_the_visible_pair_score(self):
        registration = self.registration()
        default, _ = CPUReranker(registration).score('x', ['y', 'x x x', 'x', 'y y', 'x x'])
        bounded, _ = CPUReranker(registration, batch_size=1).score('x', ['y', 'x x x', 'x', 'y y', 'x x'])
        self.assertEqual(default, [29., 30., 28., 31., 29.])
        self.assertEqual(bounded, default)

    def test_invalid_batch_bound_is_rejected(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CPUReranker(self.registration(), batch_size=value)

    def test_explicit_cpu_budget_preserves_real_pair_scoring(self):
        runtime = CPUReranker(self.registration(batch=1), batch_size=1, intra_op_threads=4)
        scores, _ = runtime.score('x', ['y', 'x x x', 'x', 'y y'])
        self.assertEqual(scores, [29., 30., 28., 31.])

    def test_invalid_cpu_budget_cannot_silently_select_all_cores(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CPUReranker(self.registration(), intra_op_threads=value)


if __name__ == '__main__':
    unittest.main()
