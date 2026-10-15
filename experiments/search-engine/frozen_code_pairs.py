"""Experimental joint code evidence from an already loaded frozen CPU graph."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


class FrozenCodePairs:
    """Own paired tokenization and unit CLS projection; never load model weights."""
    def __init__(self, session: Any, tokenizer: Any, *, query_prefix: str,
                 dimension: int, max_tokens: int = 512):
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
               for value in (dimension, max_tokens)):
            raise ValueError('positive integer pair dimension and token budget required')
        if session.get_providers() != ['CPUExecutionProvider']:
            raise ValueError('only the frozen CPU execution provider is allowed')
        if not isinstance(query_prefix, str):
            raise ValueError('registered query prefix required')
        self.names = {item.name for item in session.get_inputs()}
        if (not {'input_ids', 'attention_mask'} <= self.names
                or not self.names <= {'input_ids', 'attention_mask', 'token_type_ids'}):
            raise ValueError('unsupported frozen pair graph inputs')
        self.session, self.dimension, self.query_prefix = session, dimension, query_prefix
        self.tokenizer = type(tokenizer).from_str(tokenizer.to_str())
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(max_length=max_tokens, strategy='only_second')

    def encode(self, query: str, documents: Sequence[str]) -> np.ndarray:
        if not isinstance(query, str) or any(not isinstance(doc, str) for doc in documents):
            raise ValueError('query and source documents must be text')
        rows = []
        for document in documents:
            tokens = self.tokenizer.encode(self.query_prefix+query, document)
            attributes = {'input_ids': tokens.ids, 'attention_mask': tokens.attention_mask,
                          'token_type_ids': tokens.type_ids}
            inputs = {name: np.array([attributes[name]], dtype=np.int64) for name in self.names}
            raw = np.asarray(self.session.run(['sentence_embedding'], inputs)[0])
            if (raw.shape != (1, self.dimension) or raw.dtype != np.float32
                    or not np.isfinite(raw).all()):
                raise ValueError('one finite float32 joint CLS vector required')
            real = np.array(raw[0], dtype=np.float64, copy=True)
            scale = np.max(np.abs(real))
            if scale == 0:
                raise ValueError('joint CLS direction must be nonzero')
            scaled = real/scale
            rows.append(np.asarray(scaled/np.linalg.norm(scaled), dtype=np.float32))
        return np.stack(rows) if rows else np.empty((0, self.dimension), dtype=np.float32)
