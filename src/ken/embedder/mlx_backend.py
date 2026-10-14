"""Optional Qwen3 encoder using the same pinned weights on Apple's MLX runtime."""
from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

_MEMORY_LOCK = threading.Lock()


def bound_free_cache(runtime: Any) -> None:
    """Bound retired buffers, without limiting live weights or raising host limits."""
    budget = 512 * 1024**2
    with _MEMORY_LOCK:
        prior = runtime.set_cache_limit(budget)
        if prior < budget:
            runtime.set_cache_limit(prior)


@lru_cache(maxsize=4)
def model_snapshot(spec: Any) -> Path:
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(spec.model_id, revision=spec.revision,
                                   local_files_only=True, token=False))


@lru_cache(maxsize=4)
def model_tokenizer(spec: Any):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(model_snapshot(spec), local_files_only=True,
                                          trust_remote_code=False, padding_side="right")


def load_qwen_core(spec: Any, *, output_tokens: tuple[str, ...] = ()):
    import mlx.core as mx
    from mlx_lm.models.qwen3 import ModelArgs, Qwen3Model
    bound_free_cache(mx)
    path = model_snapshot(spec)
    config = json.loads((path / "config.json").read_text())
    if config.get("model_type") != "qwen3":
        raise ValueError("MLX retrieval backend currently supports Qwen3 only")
    model = Qwen3Model(ModelArgs.from_dict(config))
    weights = {}
    head = None
    for file in sorted(path.glob("*.safetensors")):
        loaded = mx.load(str(file))
        if not isinstance(loaded, dict):
            raise ValueError("model safetensors must contain named weights")
        for name, value in loaded.items():
            if name == "lm_head.weight":
                if output_tokens:
                    head = value
                continue
            weights[name.removeprefix("model.")] = value.astype(getattr(mx, spec.dtype))
    model.load_weights(list(weights.items()), strict=True)
    mx.eval(model.parameters())
    tokenizer = model_tokenizer(spec)
    output_weights = None
    if output_tokens:
        if head is None:
            if not config.get("tie_word_embeddings"):
                raise ValueError("missing language model output weights")
            head = model.embed_tokens.weight
        ids = mx.array([tokenizer.convert_tokens_to_ids(token) for token in output_tokens])
        output_weights = head[ids].astype(mx.float32)
        mx.eval(output_weights)
    return model, tokenizer, output_weights


class MLXEncoder:
    def __init__(self, spec: Any) -> None:
        self.spec = spec
        self._model: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()
        from ken.embedder import prompts_for
        self._query_prompt, self._passage_prompt = prompts_for(spec.model_id)

    def _load(self) -> None:
        if self._model is not None:
            return
        self._model, self._tokenizer, _ = load_qwen_core(self.spec)

    def token_count(self, text: str) -> int:
        with self._lock:
            return len(model_tokenizer(self.spec).encode(text, add_special_tokens=False))

    def _encode(self, texts: list[str]) -> list[np.ndarray]:
        import mlx.core as mx
        with self._lock:
            self._load()
            encoded = self._tokenizer(texts, truncation=True,
                max_length=self.spec.sequence_length)["input_ids"]
            order = sorted(range(len(encoded)), key=lambda i: len(encoded[i]))
            result: list[np.ndarray] = [np.empty(0)] * len(texts)
            for start in range(0, len(order), self.spec.batch_size):
                indices = order[start:start + self.spec.batch_size]
                sequences = [encoded[i] for i in indices]
                length = max(map(len, sequences))
                pad = self._tokenizer.pad_token_id
                ids = mx.array([s + [pad] * (length - len(s)) for s in sequences])
                hidden = self._model(ids)
                # Right padding follows every real token; causal attention cannot
                # affect the real prefix. Gather the last real position per row.
                pooled = hidden[mx.arange(len(indices)), mx.array([len(s)-1 for s in sequences])]
                mx.eval(pooled)
                values = np.asarray(pooled.astype(mx.float32))
                norms = np.linalg.norm(values, axis=1, keepdims=True)
                if not np.isfinite(values).all() or (norms <= 0).any():
                    raise ValueError("MLX encoder returned invalid vectors")
                values = values / norms
                for i, vector in zip(indices, values, strict=True):
                    result[i] = vector
            return result

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return self._encode([self._passage_prompt + text for text in texts]) if texts else []

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self._query_prompt + text])[0]
