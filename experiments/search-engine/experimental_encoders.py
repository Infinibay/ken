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
