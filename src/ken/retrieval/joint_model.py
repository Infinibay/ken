"""Local causal relevance model with bounded inputs and two-token output projection."""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from importlib import import_module
from typing import Any

import numpy as np

from ken.retrieval.profile import EncoderSpec

logger = logging.getLogger(__name__)
PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
          'and the Instruct provided. Note that the answer can only be "yes" or "no".'
          '<|im_end|>\n<|im_start|>user\n')
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
INSTRUCTIONS = {
    "implementation": "Find the code implementation that performs the requested behavior, including its conditions and effects.",
    "tests": "Find the test code that verifies the requested behavior.",
    "usage": "Find example or caller code demonstrating the requested usage.",
    "documentation": "Find documentation explaining the requested behavior.",
    "identity": "Find the requested code declaration, matching its exact name and kind.",
}


def project_last_token(hidden: Any, attention_mask: Any, weights: Any, *,
                       true_id: int, false_id: int) -> Any:
    import torch
    last = attention_mask.sum(dim=1).long() - 1
    states = hidden[torch.arange(hidden.shape[0], device=hidden.device), last]
    return states.float() @ (weights[true_id].float() - weights[false_id].float())


class LocalRelevanceJudge:
    def __init__(self, spec: EncoderSpec) -> None:
        self.spec = spec
        self._lock = threading.Lock()
        self._model: Any = None
        self._tokenizer: Any = None
        self.device = "unknown"
        self._output_weights: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        if self.spec.backend == "mlx":
            from ken.embedder.mlx_backend import load_qwen_core
            self._model, self._tokenizer, self._output_weights = load_qwen_core(
                self.spec, output_tokens=("yes", "no"))
            self.device = "mlx"
            return
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from ken.embedder.st_backend import _resolve_device
        path = snapshot_download(self.spec.model_id, revision=self.spec.revision,
                                 local_files_only=True, token=False)
        self.device = _resolve_device()
        self._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True,
            trust_remote_code=False, padding_side="right")
        self._model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True,
            trust_remote_code=False, torch_dtype=getattr(torch, self.spec.dtype)).eval().to(self.device)
        if self._model.config.model_type != "qwen3":
            raise ValueError("joint relevance backend requires the Qwen3 causal architecture")

    def _run(self, query: str, documents: list[str], purpose: str) -> np.ndarray:
        tokenizer = self._tokenizer
        prefix = tokenizer.encode(PREFIX, add_special_tokens=False)
        suffix = tokenizer.encode(SUFFIX, add_special_tokens=False)
        query_ids = tokenizer.encode(query, add_special_tokens=False)[:128]
        header = tokenizer.encode("<Instruct>: " + INSTRUCTIONS.get(purpose, INSTRUCTIONS["implementation"])
            + "\n<Query>: ", add_special_tokens=False) + query_ids + tokenizer.encode("\n<Document>: ", add_special_tokens=False)
        remaining = self.spec.sequence_length - len(prefix) - len(header) - len(suffix)
        if remaining < 16:
            raise ValueError("joint model sequence budget cannot contain query and source")
        encoded = tokenizer(documents, add_special_tokens=False, truncation=True,
                            max_length=remaining)["input_ids"]
        scores = []
        true_id = tokenizer.convert_tokens_to_ids("yes")
        false_id = tokenizer.convert_tokens_to_ids("no")
        if self.device == "mlx":
            mx = import_module("mlx.core")
            for start in range(0, len(encoded), self.spec.batch_size):
                sequences = [prefix + header + ids + suffix
                             for ids in encoded[start:start + self.spec.batch_size]]
                length = max(map(len, sequences))
                ids = mx.array([s + [tokenizer.pad_token_id] * (length - len(s)) for s in sequences])
                hidden = self._model(ids)
                last = hidden[mx.arange(len(sequences)), mx.array([len(s)-1 for s in sequences])]
                logits = last.astype(mx.float32) @ (self._output_weights[0] - self._output_weights[1])
                mx.eval(logits)
                scores.extend(np.asarray(logits).tolist())
            return np.asarray(scores, dtype=np.float32)
        import torch
        with torch.inference_mode():
            for start in range(0, len(encoded), self.spec.batch_size):
                sequences = [prefix + header + ids + suffix
                             for ids in encoded[start:start + self.spec.batch_size]]
                batch = tokenizer.pad({"input_ids": sequences}, padding=True, return_tensors="pt")
                batch = {name: value.to(self.device) for name, value in batch.items()}
                hidden = self._model.model(**batch).last_hidden_state
                logits = project_last_token(hidden, batch["attention_mask"], self._model.lm_head.weight,
                                            true_id=true_id, false_id=false_id)
                scores.extend(logits.cpu().tolist())
        return np.asarray(scores, dtype=np.float32)

    def score(self, query: str, documents: list[str], *, purpose: str) -> np.ndarray:
        with self._lock:
            self._load()
            try:
                scores = self._run(query, documents, purpose)
                if not np.isfinite(scores).all():
                    raise ValueError("non-finite relevance logits")
                return scores
            except (RuntimeError, ValueError) as exc:
                if self.device in ("cpu", "mlx"):
                    raise
                import torch
                logger.warning("joint relevance on %s failed (%s); retrying on CPU", self.device, exc)
                self._model = self._model.to(device="cpu", dtype=torch.float32)
                self.device = "cpu"
                scores = self._run(query, documents, purpose)
                if not np.isfinite(scores).all():
                    raise ValueError("non-finite CPU relevance logits")
                return scores


@lru_cache(maxsize=1)
def load_judge(spec: EncoderSpec) -> LocalRelevanceJudge:
    return LocalRelevanceJudge(spec)
