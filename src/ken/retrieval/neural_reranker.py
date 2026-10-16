"""Lazy, bounded joint scoring over an already chosen native top10."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class RerankerAssets:
    graph: Path
    graph_sha256: str
    tokenizer: Path
    tokenizer_sha256: str
    config: Path
    config_sha256: str
    tokenizer_config: Path
    tokenizer_config_sha256: str

    @classmethod
    def from_registration(cls, record: Mapping[str, Any]) -> RerankerAssets:
        upstream = record['upstream']
        root = Path(upstream['root'])
        def digest(name: str) -> str:
            expected = upstream['artifacts'][name]
            return expected['sha256'] if isinstance(expected, dict) else expected
        return cls(Path(record['graph']), record['graph_sha256'],
            Path(record['tokenizer']), record['tokenizer_sha256'],
            root/'config.json', digest('config.json'),
            root/'tokenizer_config.json', digest('tokenizer_config.json'))

    def verify(self) -> None:
        for path, expected in ((self.graph, self.graph_sha256),
                (self.tokenizer, self.tokenizer_sha256), (self.config, self.config_sha256),
                (self.tokenizer_config, self.tokenizer_config_sha256)):
            if not re.fullmatch('[a-f0-9]{64}', expected) or not path.is_file():
                raise ValueError('registered reranker artifact required')
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected:
                raise ValueError(f'registered reranker artifact changed: {path.name}')


class ONNXReranker:
    """Preserve raw logits and document order; fusion owns the final ordering."""

    def __init__(self, prepare: Callable[[], RerankerAssets], *, batch_size: int = 1,
                 intra_op_threads: int = 4, max_tokens: int = 1024) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError('positive integer batch size required')
        if type(intra_op_threads) is not int or intra_op_threads < 1:
            raise ValueError('positive integer CPU thread budget required')
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError('positive integer token budget required')
        self._max_tokens = max_tokens
        self._prepare, self.batch_size = prepare, batch_size
        self._threads = intra_op_threads
        self._session: Any = None
        self._tokenizer: Any = None
        self._query_tokenizer: Any = None
        self._output = ''
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            assets = self._prepare()
            assets.verify()
            Tokenizer = import_module('tokenizers').Tokenizer
            tokenizer = Tokenizer.from_file(str(assets.tokenizer))
            config = json.loads(assets.config.read_bytes())
            token_config = json.loads(assets.tokenizer_config.read_bytes())
            for limit in (config.get('max_position_embeddings'), token_config.get('model_max_length')):
                if limit is not None and (type(limit) is not int or limit < 1 or self._max_tokens > limit):
                    raise ValueError('token budget exceeds or conflicts with declared model limit')
            tokenizer.enable_truncation(max_length=self._max_tokens, strategy='only_second')
            token = token_config['pad_token']
            if isinstance(token, dict):
                token = token['content']
            token_id = config['pad_token_id']
            side = token_config.get('padding_side', 'right')
            if type(token_id) is not int or tokenizer.token_to_id(token) != token_id or side != 'right':
                raise ValueError('inconsistent published padding configuration')
            tokenizer.enable_padding(pad_id=token_id, pad_token=token, direction=side)
            query_tokenizer = Tokenizer.from_file(str(assets.tokenizer))
            query_tokenizer.no_padding()
            query_tokenizer.no_truncation()
            ort = import_module('onnxruntime')
            options = ort.SessionOptions()
            options.intra_op_num_threads = self._threads
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(assets.graph), sess_options=options,
                                           providers=['CPUExecutionProvider'])
            if session.get_providers() != ['CPUExecutionProvider']:
                raise ValueError('CPU reranker provider required')
            self._tokenizer, self._query_tokenizer = tokenizer, query_tokenizer
            self._output = session.get_outputs()[0].name
            self._session = session

    @property
    def providers(self) -> tuple[str, ...]:
        self._load()
        return tuple(self._session.get_providers())

    def pair_fits(self, query: str, text: str) -> bool:
        """Check complete pair capacity without truncation or model inference."""
        self._load()
        return len(self._query_tokenizer.encode(query, text).ids) <= self._max_tokens

    def score(self, query: str, texts: Sequence[str]) -> tuple[list[float], dict[str, Any]]:
        if len(texts) > 10:
            raise ValueError('reranking is limited to the native top10')
        scores: list[float] = []
        details: dict[str, Any] = {'token_ms': 0., 'inference_ms': 0.,
                                  'truncated_documents': 0, 'pair_tokens': []}
        if not texts:
            return scores, details
        self._load()
        special = self._tokenizer.num_special_tokens_to_add(True)
        if len(query) > 65536 or len(self._query_tokenizer.encode(query, add_special_tokens=False).ids) > self._max_tokens-special-1:
            raise ValueError('query is too long for reranking; shorten the search question')
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start+self.batch_size]
            before = time.perf_counter()
            encoded = self._tokenizer.encode_batch([(query, text) for text in batch])
            details['truncated_documents'] += sum(bool(e.overflowing) for e in encoded)
            details['pair_tokens'].extend(sum(e.attention_mask) for e in encoded)
            feeds = {'input_ids': np.array([e.ids for e in encoded], np.int64),
                     'attention_mask': np.array([e.attention_mask for e in encoded], np.int64)}
            details['token_ms'] += (time.perf_counter()-before)*1000
            before = time.perf_counter()
            result = self._session.run([self._output], feeds)[0].reshape(-1)
            details['inference_ms'] += (time.perf_counter()-before)*1000
            if len(result) != len(batch) or not np.isfinite(result).all():
                raise ValueError('reranker must return one finite score per document')
            scores.extend(float(value) for value in result)
        details['pad_id'] = self._tokenizer.padding['pad_id']
        return scores, details
