"""Immutable, serializable retrieval configuration; no repository-specific knobs."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

import numpy as np


class Encoder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[np.ndarray]: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


@lru_cache(maxsize=4)
def _backend_runtime(backend: str) -> tuple[tuple[str, str], ...]:
    packages = {
        "static": ("numpy", "tokenizers"),
        "sentence-transformers": ("numpy", "torch", "transformers", "tokenizers", "sentence-transformers", "huggingface-hub"),
        "mlx": ("numpy", "mlx", "mlx-lm", "transformers", "tokenizers", "huggingface-hub"),
        "provided": (),
    }[backend]
    return tuple((name, _package_version(name)) for name in packages)


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
        if self.backend not in ("static", "sentence-transformers", "provided", "mlx"):
            raise ValueError("unknown encoder backend")
        if self.dtype not in ("float32", "float16", "bfloat16"):
            raise ValueError("unknown encoder dtype")
        if self.sequence_length <= 0 or self.batch_size <= 0:
            raise ValueError("positive encoder sequence and batch budgets required")

    @property
    def key(self) -> str:
        options = hashlib.sha256(json.dumps({"config": asdict(self),
            "runtime": _backend_runtime(self.backend)}, sort_keys=True).encode()).hexdigest()
        return self.model_id + "@" + self.revision + ":" + options[:16]

    @property
    def tokenizer_revision(self) -> str:
        runtime = tuple(item for item in _backend_runtime(self.backend)
                        if item[0] in ("transformers", "tokenizers"))
        return hashlib.sha256(json.dumps(runtime).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class JointRanking:
    model: EncoderSpec
    candidate_limit: int = 100
    rank_unit: str = "passage"
    evidence_results: int = 1
    max_windows: int = 6
    max_fragments: int = 3

    def __post_init__(self) -> None:
        if self.rank_unit not in ("entity", "passage"):
            raise ValueError("unknown relevance unit")
        if (self.candidate_limit <= 0 or self.evidence_results < 0 or self.max_windows <= 0
                or not 1 <= self.max_fragments <= 4):
            raise ValueError("invalid relevance/evidence budgets")


@dataclass(frozen=True)
class RetrievalProfile:
    identity: EncoderSpec
    behavior: EncoderSpec
    max_tokens: int = 256
    candidate_limit: int = 100
    rrf_k: int = 60
    passage_tokenizer: str = "code-lexical-v1"
    representation_version: int = 3
    joint: JointRanking | None = None

    def __post_init__(self) -> None:
        if self.max_tokens <= 0 or self.candidate_limit <= 0 or self.rrf_k <= 0:
            raise ValueError("positive retrieval budgets required")
        if self.passage_tokenizer not in ("code-lexical-v1", "behavior-model"):
            raise ValueError("unknown source passage tokenizer")
        if self.representation_version != 3:
            raise ValueError("unsupported representation version; reindex with current profile")

    def vector_revision(self, view: str) -> str:
        spec = getattr(self, view)
        projection = {"version": self.representation_version, "view": view}
        digest = hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()[:16]
        return spec.key + ":projection-" + digest

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, upgrade_representation: bool = False) -> RetrievalProfile:
        data = dict(value)
        if upgrade_representation and data.get("representation_version") == 2:
            data.pop("representation_version")
        data["identity"] = EncoderSpec(**data["identity"])
        data["behavior"] = EncoderSpec(**data["behavior"])
        if data.get("joint") is not None:
            joint = dict(data["joint"])
            joint["model"] = EncoderSpec(**joint["model"])
            data["joint"] = JointRanking(**joint)
        return cls(**data)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps({"config": self.to_dict(), "runtime": {
            "identity": _backend_runtime(self.identity.backend),
            "behavior": _backend_runtime(self.behavior.backend),
            "joint": _backend_runtime(self.joint.model.backend) if self.joint else ()}}, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=1)
def default_profile() -> RetrievalProfile:
    model = "ken/static-qwen3-r512-v2"
    artifact = resources.files("ken.embedder").joinpath("data/ken__static-qwen3-r512-v2.npz")
    spec = EncoderSpec(model, hashlib.sha256(artifact.read_bytes()).hexdigest())
    return RetrievalProfile(spec, spec)


def active_profile(conn: sqlite3.Connection, *, upgrade_for_indexing: bool = False) -> RetrievalProfile:
    from ken.retrieval.embedding_store import IndexVersionError
    row = conn.execute("SELECT value FROM meta WHERE key='retrieval_profile'").fetchone()
    try:
        return (RetrievalProfile.from_dict(json.loads(row[0]), upgrade_representation=upgrade_for_indexing)
                if row else default_profile())
    except (ValueError, TypeError, KeyError) as exc:
        raise IndexVersionError(f"stored retrieval profile needs reindexing: {exc}") from exc


@lru_cache(maxsize=4)
def load_encoder(spec: EncoderSpec) -> Encoder:
    if spec.backend == "mlx":
        from ken.embedder.mlx_backend import MLXEncoder
        return MLXEncoder(spec)
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
