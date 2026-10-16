"""Pinned, lazy CPU contextual embeddings with the measured raw-CLS policy."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from importlib import resources, import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from ken.model_assets import ModelAssets
from ken.retrieval.profile import EncoderSpec


@dataclass(frozen=True)
class ContextModel:
    assets: ModelAssets
    query_prefix: str
    document_projection: str

    def __post_init__(self) -> None:
        if {a.path for a in self.assets.artifacts} != {'onnx/model.onnx', 'tokenizer.json'}:
            raise ValueError('context model requires its graph and tokenizer')
        if not self.document_projection:
            raise ValueError('context model requires a source projection identity')

    @property
    def spec(self) -> EncoderSpec:
        # Preserve the measured identity, including tokenizer/runtime versions.
        identity = {'model_id': self.assets.model_id, 'upstream_revision': self.assets.revision,
            'artifacts': {a.path: a.sha256 for a in self.assets.artifacts},
            'query_prefix': self.query_prefix, 'document_projection': self.document_projection,
            'policy': 'CPU-raw-CLS-runtime-L2-no-padding-prefix512-batch1-v1',
            'runtime': {'numpy': np.__version__, 'onnxruntime': version('onnxruntime'),
                        'tokenizers': version('tokenizers')}}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return EncoderSpec(self.assets.model_id, digest, 'provided', sequence_length=512, batch_size=1)


class ContextEncoder:
    """Return raw model vectors; contextual retrieval owns explicit L2 scoring."""

    def __init__(self, model: ContextModel, *, snapshot: Path | None = None,
                 cache_dir: Path | None = None, local_files_only: bool = False) -> None:
        self.model, self.spec = model, model.spec
        self._snapshot, self._cache_dir = snapshot, cache_dir
        self._local_files_only = local_files_only
        self._session: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            ort = import_module("onnxruntime")
            Tokenizer = import_module("tokenizers").Tokenizer
            root = (self.model.assets.verify(self._snapshot) if self._snapshot is not None
                    else self.model.assets.resolve(cache_dir=self._cache_dir,
                                                   local_files_only=self._local_files_only))
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(root / 'onnx/model.onnx'), sess_options=options,
                                           providers=['CPUExecutionProvider'])
            if session.get_providers() != ['CPUExecutionProvider']:
                raise ValueError('CPU contextual provider required')
            tokenizer = Tokenizer.from_file(str(root / 'tokenizer.json'))
            tokenizer.no_padding()
            tokenizer.enable_truncation(max_length=512)
            self._tokenizer, self._session = tokenizer, session

    @property
    def providers(self) -> tuple[str, ...]:
        self._load()
        return tuple(self._session.get_providers())

    def _encode(self, text: str) -> np.ndarray:
        self._load()
        tokens = self._tokenizer.encode(text)
        inputs = {'input_ids': np.array([tokens.ids], dtype=np.int64),
                  'attention_mask': np.array([tokens.attention_mask], dtype=np.int64)}
        vector = self._session.run(['sentence_embedding'], inputs)[0][0]
        if vector.shape != (768,) or vector.dtype != np.float32 or not np.isfinite(vector).all():
            raise ValueError('invalid contextual embedding')
        return vector

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode(self.model.query_prefix + query)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self._encode(text) for text in texts]


def code_context_model() -> ContextModel:
    data = json.loads(resources.files('ken.embedder').joinpath('data/code-context-int8.json').read_text())
    return ContextModel(ModelAssets.from_dict(data), data['query_prefix'], data['document_projection'])
