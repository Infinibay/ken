import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tokenizers import Tokenizer, models, pre_tokenizers
from ettin_cpu import CPUReranker


class PublishedPadding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        vocab = {'[UNK]': 0, 'x': 1, **{f'unused{i}': i for i in range(2, 7)}, '[PAD]': 7}
        tokenizer = Tokenizer(models.WordLevel(vocab, unk_token='[UNK]'))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.save(str(self.root / 'tokenizer.json'))
        (self.root / 'graph.onnx').write_bytes(b'test graph; session stubbed')
        (self.root / 'config.json').write_text(json.dumps({'pad_token_id': 7}))
        (self.root / 'tokenizer_config.json').write_text(json.dumps({'pad_token': '[PAD]', 'padding_side': 'right'}))
        def sha(name):
            return hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        self.registration = {'graph': str(self.root / 'graph.onnx'), 'graph_sha256': sha('graph.onnx'),
            'tokenizer': str(self.root / 'tokenizer.json'), 'tokenizer_sha256': sha('tokenizer.json'),
            'upstream': {'root': str(self.root), 'artifacts': {name: {'sha256': sha(name)}
                for name in ('config.json', 'tokenizer_config.json')}}}
        self.fake = SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider'],
                                    get_outputs=lambda: [SimpleNamespace(name='scores')])

    def tearDown(self):
        self.tmp.cleanup()

    def test_runtime_uses_published_padding_id_in_actual_batch(self):
        with patch('ettin_cpu.ort.InferenceSession', return_value=self.fake):
            runtime = CPUReranker(self.registration)
        batch = runtime.tokenizer.encode_batch([('x', 'x x'), ('x', 'x')])
        self.assertEqual(runtime.tokenizer.padding['pad_id'], 7)
        self.assertEqual(batch[1].ids[-1], 7)
        self.assertEqual(batch[1].attention_mask[-1], 0)

    def test_changed_configuration_is_rejected(self):
        (self.root / 'config.json').write_text(json.dumps({'pad_token_id': 99}))
        with patch('ettin_cpu.ort.InferenceSession', return_value=self.fake), self.assertRaises(ValueError):
            CPUReranker(self.registration)


if __name__ == '__main__':
    unittest.main()
