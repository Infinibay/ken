"""Optional development controls; none is silently selected by the public engine."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from ken.retrieval.profile import EncoderSpec


class PotionControl:
    def __init__(self, snapshot: Path):
        from model2vec import StaticModel
        self.spec = EncoderSpec("minishlab/potion-code-16M-v2",
            "e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b", "provided", dtype="float16")
        if not snapshot.is_dir() or snapshot.name != self.spec.revision:
            raise ValueError("the Potion control requires its pinned local snapshot")
        if hashlib.sha256((snapshot / "model.safetensors").read_bytes()).hexdigest() != (
                "75cf7a6c2171b230ad19b1e7d8e0b1aee86da5a02af8e7cacedd9921d227623c"):
            raise ValueError("Potion weights do not match registration")
        self.model = StaticModel.from_pretrained(snapshot, normalize=True, force_download=False)

    def token_count(self, text: str) -> int:
        return len(self.model.tokenize([text], max_length=None)[0])

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        return [np.asarray(v, dtype=np.float32) for v in self.model.encode(texts,
            max_length=self.spec.sequence_length, use_multiprocessing=False, batch_size=1024)]

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


class ColbertControl:
    """Pinned 33M multilingual control, standard BERT + linear projection on CPU."""
    def __init__(self, snapshot: Path, cache: Path, *, query_length: int = 64,
                 document_length: int = 300, batch_size: int = 8):
        import json
        import torch
        from safetensors.torch import load_file
        from transformers import AutoModel, AutoTokenizer
        from ken.bench.late_interaction import DocumentVectors
        revision = '013759e3bc6ec5688b58f84e98a59e5a2cde4171'
        if snapshot.name != revision:
            raise ValueError('registered ColBERT revision required')
        expected = {'model.safetensors': '13b4a955fce6dc3285322e5c89cfbdd32e17f0b92b910b4715091513b07fb501',
                    '1_Dense/model.safetensors': '2f7099bc3cd07dea9d8ddc87820d38cc70aee52f2b76185ac8fd64d5d22c7167'}
        for name, digest in expected.items():
            if hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != digest:
                raise ValueError('ColBERT weights changed')
        metadata = json.loads((snapshot/'config_sentence_transformers.json').read_text())
        dense = json.loads((snapshot/'1_Dense/config.json').read_text())
        if dense != {'in_features': 384, 'out_features': 128, 'bias': False,
                     'activation_function': 'torch.nn.modules.linear.Identity'}:
            raise ValueError('unsupported document projection')
        self.tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        self.tokenizer.pad_token_id = self.tokenizer.mask_token_id
        self.prefixes = {True: self.tokenizer.convert_tokens_to_ids(metadata['query_prefix']),
                         False: self.tokenizer.convert_tokens_to_ids(metadata['document_prefix'])}
        self.skiplist = {self.tokenizer.convert_tokens_to_ids(s) for s in metadata['skiplist_words']}
        self.model = AutoModel.from_pretrained(snapshot, local_files_only=True,
            trust_remote_code=False, attn_implementation='sdpa').to('cpu').eval()
        weights = load_file(str(snapshot/'1_Dense/model.safetensors'), device='cpu')
        self.projection = weights['linear.weight'].T.contiguous()
        self.query_length, self.document_length, self.batch_size = query_length, document_length, batch_size
        self.revision = hashlib.sha256(json.dumps({'model': revision, 'files': expected,
            'query_length': query_length, 'document_length': document_length,
            'dtype': 'float32', 'device': 'cpu', 'torch': torch.__version__,
            'tokenization': 'pylate-mask-expansion-v1'}, sort_keys=True).encode()).hexdigest()
        self.cache = DocumentVectors(cache, self.revision, self.encode_documents)

    def encode(self, texts: list[str], *, query: bool) -> list[np.ndarray]:
        import torch
        from ken.bench.late_interaction import prepare_features
        output = []
        for start in range(0, len(texts), self.batch_size):
            features = prepare_features(self.tokenizer, texts[start:start+self.batch_size],
                prefix_id=self.prefixes[query], length=self.query_length if query else self.document_length,
                query=query)
            with torch.inference_mode():
                vectors = torch.nn.functional.normalize(
                    self.model(**features).last_hidden_state @ self.projection, p=2, dim=2).numpy()
            for i, vector in enumerate(vectors):
                mask = np.ones(len(vector), dtype=bool) if query else (
                    features['attention_mask'][i].numpy().astype(bool)
                    & ~np.isin(features['input_ids'][i].numpy(), list(self.skiplist)))
                output.append(vector[mask])
        return output

    def encode_documents(self, texts: list[str]) -> list[np.ndarray]:
        return self.encode(texts, query=False)

    def score(self, query: str, documents: list[str], *, purpose: str) -> list[float]:
        from ken.bench.late_interaction import maxsim
        vector = self.encode([query], query=True)[0]
        return [maxsim(vector, doc) for doc in self.cache.get_many(documents)]


class MiniLMOnnxControl:
    """Official 119MB ARM64 int8 relevance control with CPU-only execution."""
    def __init__(self, snapshot: Path, *, max_tokens: int = 512, batch_size: int = 8):
        import json
        import onnxruntime as ort
        import tokenizers
        from tokenizers import Tokenizer
        from ken.bench.pair_relevance import PairRelevance
        if snapshot.name != '1427fd652930e4ba29e8149678df786c240d8825':
            raise ValueError('registered MiniLM revision required')
        expected = {'onnx/model_qint8_arm64.onnx':'1825907d6c1a9001ff78124780bbde20a614a8c3df3b63409cf3c72c6fe5c8b4',
                    'tokenizer.json':'62c24cdc13d4c9952d63718d6c9fa4c287974249e16b7ade6d5a85e7bbb75626'}
        for name,digest in expected.items():
            if hashlib.sha256((snapshot/name).read_bytes()).hexdigest() != digest:
                raise ValueError('registered MiniLM artifact changed')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(snapshot/'onnx/model_qint8_arm64.onnx'),
            sess_options=options, providers=['CPUExecutionProvider'])
        if session.get_providers() != ['CPUExecutionProvider']:
            raise ValueError('CPU-only model provider required')
        tokenizer = Tokenizer.from_file(str(snapshot/'tokenizer.json'))
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id('<pad>'), pad_token='<pad>')
        self.judge = PairRelevance(session, tokenizer, max_tokens=max_tokens, batch_size=batch_size)
        self.revision = hashlib.sha256(json.dumps({'files':expected, 'onnxruntime':ort.__version__,
            'tokenizers':tokenizers.__version__, 'max_tokens':max_tokens,'batch_size':batch_size,
            'provider':session.get_providers(),'intra_op_threads':2,'inter_op_threads':1},sort_keys=True).encode()).hexdigest()

    def score(self, query: str, documents: list[str], *, purpose: str) -> list[float]:
        return self.judge.score(query,documents,purpose=purpose)
