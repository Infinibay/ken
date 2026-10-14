"""Registered, offline Model2Vec controls for matched CPU experiments."""
from __future__ import annotations

import hashlib
import json
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from ken.retrieval.profile import EncoderSpec


class StaticEmbeddingControl:
    """Bind local weights, tokenizer, runtime and pooling to one immutable profile."""

    def __init__(self, snapshot: Path, registration: Mapping[str, Any], *,
                 loader: Callable[..., Any] | None = None) -> None:
        if not snapshot.is_dir() or snapshot.name != registration['revision']:
            raise ValueError('registered static model revision required')
        artifacts = {name: dict(expected) for name, expected in registration['artifacts'].items()}
        if not any(name.endswith('.safetensors') for name in artifacts):
            raise ValueError('registered static weights required')
        if not any(name.endswith('tokenizer.json') for name in artifacts):
            raise ValueError('registered tokenizer artifact required')
        for name, expected in artifacts.items():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('registered artifact path must be local and relative')
            path = snapshot / name
            # Hugging Face snapshots use symlinks to content-addressed blobs.
            if not path.is_file():
                raise ValueError('registered artifact is missing from the local snapshot')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if path.stat().st_size != expected['bytes'] or digest != expected['sha256']:
                raise ValueError(f'registered static artifact changed: {name}')
        if loader is None:
            loader = import_module('model2vec').StaticModel.from_pretrained
        self.model = loader(snapshot, normalize=True, force_download=False)
        dtype = str(self.model.embedding.dtype)
        if dtype not in ('float16', 'float32'):
            raise ValueError('control requires native float16 or float32 static weights')
        self.identity = {
            'model_id': registration['model_id'], 'hf_revision': registration['revision'],
            'artifacts': artifacts, 'dtype': dtype, 'dimension': int(self.model.embedding.shape[1]),
            'runtime': {p: version(p) for p in ('numpy', 'model2vec', 'tokenizers', 'safetensors')},
            'pooling': 'model2vec-native-mean-L2-v1', 'sequence_length': 512,
            'multiprocessing': False, 'batch_size': 1024, 'device': 'cpu',
        }
        revision = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self.spec = EncoderSpec(registration['model_id'], revision, 'provided', dtype=dtype)

    def token_count(self, text: str) -> int:
        return len(self.model.tokenize([text], max_length=None)[0])

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        vectors = self.model.encode(texts, max_length=self.spec.sequence_length,
            use_multiprocessing=False, batch_size=1024)
        return [np.asarray(v, dtype=np.float32) for v in vectors]

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]
