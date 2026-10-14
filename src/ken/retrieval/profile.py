"""Immutable, serializable retrieval configuration; no repository-specific knobs."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Protocol

import numpy as np


class Encoder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...


@dataclass(frozen=True)
class EncoderSpec:
    model_id: str
    revision: str
    backend: str = "static"
    dtype: str = "float32"
    sequence_length: int = 512
    batch_size: int = 16

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", self.revision):
            raise ValueError("an immutable model revision/hash is required")
        if self.backend not in ("static", "sentence-transformers", "provided"):
            raise ValueError("unknown encoder backend")
        if self.dtype not in ("float32", "float16", "bfloat16"):
            raise ValueError("unknown encoder dtype")
        if self.sequence_length <= 0 or self.batch_size <= 0:
            raise ValueError("positive encoder sequence and batch budgets required")

    @property
    def key(self) -> str:
        options = hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
        return self.model_id + "@" + self.revision + ":" + options[:16]


@dataclass(frozen=True)
class RetrievalProfile:
    identity: EncoderSpec
    behavior: EncoderSpec
    max_tokens: int = 256
    candidate_limit: int = 100
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if self.max_tokens <= 0 or self.candidate_limit <= 0 or self.rrf_k <= 0:
            raise ValueError("positive retrieval budgets required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RetrievalProfile:
        data = dict(value)
        data["identity"] = EncoderSpec(**data["identity"])
        data["behavior"] = EncoderSpec(**data["behavior"])
        return cls(**data)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=1)
def default_profile() -> RetrievalProfile:
    model = "ken/static-qwen3-r512-v2"
    artifact = resources.files("ken.embedder").joinpath("data/ken__static-qwen3-r512-v2.npz")
    spec = EncoderSpec(model, hashlib.sha256(artifact.read_bytes()).hexdigest())
    return RetrievalProfile(spec, spec)


@lru_cache(maxsize=4)
def load_encoder(spec: EncoderSpec) -> Encoder:
    if spec.backend == "static":
        from ken.embedder.static_head import StaticHeadEmbedder
        artifact = resources.files("ken.embedder").joinpath(
            "data/" + spec.model_id.replace("/", "__") + ".npz")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != spec.revision:
            raise ValueError("bundled model changed; rebuild with its actual revision")
        return StaticHeadEmbedder(spec.model_id)
    if spec.backend == "sentence-transformers":
        # This explicit profile path never executes remote model code.
        from ken.embedder.st_backend import SentenceTransformerEmbedder
        from huggingface_hub import snapshot_download
        snapshot = snapshot_download(spec.model_id, revision=spec.revision,
                                     local_files_only=True, token=False)
        return SentenceTransformerEmbedder(spec.model_id, revision=spec.revision,
            local_files_only=True, trust_remote_code=False, model_path=snapshot,
            dtype=spec.dtype, sequence_length=spec.sequence_length, batch_size=spec.batch_size)
    raise ValueError("provided encoders require explicit dependency injection")
