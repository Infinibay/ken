"""Pinned Model2Vec pooling shared by production and experimental controls."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from importlib import resources
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Mapping, cast

import numpy as np

from ken.model_assets import ModelAssets
from ken.retrieval.profile import EncoderSpec


_TERM_CACHE_BYTES = 8 * 1024 * 1024
_TERM_CACHE_ENTRIES = 8192
_TERM_CACHE_OVERHEAD = 256


def _cacheable_term(text: str) -> bool:
    return bool(text) and len(text) <= 128 and not any(char.isspace() for char in text)


def _term_size(text: str, vector: np.ndarray) -> int:
    return vector.nbytes + len(text.encode('utf-8')) + _TERM_CACHE_OVERHEAD


class RegisteredStaticEncoder:
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
        ModelAssets.from_dict(registration).verify(snapshot)
        if loader is None:
            loader = import_module('model2vec').StaticModel.from_pretrained
        self.model = loader(snapshot, normalize=True, force_download=False)
        # Native mean pooling consumes every returned token id, including PAD.
        # Tokenizer-wide truncation would also hide overflow from token_count.
        self.model.tokenizer.no_padding()
        self.model.tokenizer.no_truncation()
        dtype = str(self.model.embedding.dtype)
        if dtype not in ('float16', 'float32'):
            raise ValueError('control requires native float16 or float32 static weights')
        self.identity = {
            'model_id': registration['model_id'], 'hf_revision': registration['revision'],
            'artifacts': artifacts, 'dtype': dtype, 'dimension': int(self.model.embedding.shape[1]),
            'runtime': {p: version(p) for p in ('numpy', 'model2vec', 'tokenizers', 'safetensors')},
            'pooling': 'model2vec-native-mean-L2-v1', 'sequence_length': 512,
            'tokenizer_policy': 'no-padding-no-hidden-truncation-v1',
            'multiprocessing': False, 'batch_size': 1024, 'device': 'cpu',
        }
        revision = hashlib.sha256(json.dumps(self.identity, sort_keys=True).encode()).hexdigest()
        self.spec = EncoderSpec(registration['model_id'], revision, 'provided', dtype=dtype)
        self._term_vectors: OrderedDict[str, np.ndarray] = OrderedDict()
        self._term_bytes = 0
        self._term_lock = threading.Lock()

    def token_count(self, text: str) -> int:
        return len(self.model.tokenize([text], max_length=None)[0])

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        # The registered pooling is text-independent. Cache only short lexical
        # inputs; source passages and sentences must not accumulate here.
        result: list[np.ndarray | None] = [None] * len(texts)
        missing: list[int] = []
        with self._term_lock:
            for i, text in enumerate(texts):
                cached = self._term_vectors.get(text) if _cacheable_term(text) else None
                if cached is None:
                    missing.append(i)
                else:
                    self._term_vectors.move_to_end(text)
                    result[i] = cached.copy()
        if missing:
            vectors = self.model.encode([texts[i] for i in missing],
                max_length=self.spec.sequence_length, use_multiprocessing=False, batch_size=1024)
            with self._term_lock:
                for i, vector in zip(missing, vectors, strict=True):
                    value = np.asarray(vector, dtype=np.float32)
                    result[i] = value
                    text = texts[i]
                    if not _cacheable_term(text):
                        continue
                    size = _term_size(text, value)
                    if size > _TERM_CACHE_BYTES or _TERM_CACHE_ENTRIES < 1:
                        continue
                    previous = self._term_vectors.pop(text, None)
                    if previous is not None:
                        self._term_bytes -= _term_size(text, previous)
                    stored = value.copy()
                    stored.setflags(write=False)
                    self._term_vectors[text] = stored
                    self._term_bytes += size
                    while self._term_bytes > _TERM_CACHE_BYTES or len(self._term_vectors) > _TERM_CACHE_ENTRIES:
                        key, evicted = self._term_vectors.popitem(last=False)
                        self._term_bytes -= _term_size(key, evicted)
        return cast(list[np.ndarray], result)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


    @property
    def dim(self) -> int:
        return int(self.model.embedding.shape[1])

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed_passages(texts)


class Model2VecEmbedder:
    """Lazy static lookup over verified public model data; no transformer runtime."""

    def __init__(self, assets: ModelAssets, *, cache_dir: Path | None = None,
                 local_files_only: bool = False) -> None:
        self.assets = assets
        self._cache_dir = cache_dir
        self._local_files_only = local_files_only
        self._encoder: RegisteredStaticEncoder | None = None
        self._lock = threading.Lock()

    def _load(self) -> RegisteredStaticEncoder:
        if self._encoder is None:
            with self._lock:
                if self._encoder is None:
                    snapshot = self.assets.resolve(cache_dir=self._cache_dir, local_files_only=self._local_files_only)
                    self._encoder = RegisteredStaticEncoder(snapshot, self.assets.to_dict())
        return self._encoder

    @property
    def registered(self) -> RegisteredStaticEncoder:
        """Verified pooling/runtime identity for the source-feature rankers."""
        return self._load()

    @property
    def dim(self) -> int:
        return self._load().dim

    def token_count(self, text: str) -> int:
        return self._load().token_count(text)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return self._load().embed_passages(texts) if texts else []

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed_passages(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


def potion_assets() -> ModelAssets:
    """The exact winning static control, with portable upstream artifact pins."""
    artifact = resources.files('ken.embedder').joinpath('data/potion-code-16M-v2.json')
    return ModelAssets.from_dict(json.loads(artifact.read_text()))
