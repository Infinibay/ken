"""Declare the actual installed FastEmbed catalogue without loading networks."""
from __future__ import annotations

from dataclasses import asdict
import re

CONFIG_FILES = ("tokenizer.json", "tokenizer_config.json", "config.json",
                "special_tokens_map.json")
POOLING = {"OnnxTextEmbedding": "cls_or_sentence_l2", "CLIPOnnxEmbedding": "raw",
           "PooledNormalizedEmbedding": "mean_l2", "PooledEmbedding": "mean",
           "JinaEmbeddingV3": "mean_l2"}


def describe_catalogue() -> list[dict]:
    from fastembed import TextEmbedding

    return [dict(asdict(model), implementation=implementation.__name__)
            for implementation in TextEmbedding.EMBEDDINGS_REGISTRY
            for model in implementation._list_supported_models()]


def advisories(name: str) -> list[dict[str, str]]:
    # Exact messages from FastEmbed0.8.0 TextEmbedding.__init__; real captures
    # independently observe the warnings and bind the entire installed source.
    if name.lower() == "nomic-ai/nomic-embed-text-v1.5-q":
        return [{"kind": "model_update", "message":
                 "The model 'nomic-ai/nomic-embed-text-v1.5-Q' has been updated on HuggingFace. Please review "
                 "the latest documentation on HF and release notes to ensure compatibility with your workflow. "}]
    if name.lower() in {"sentence-transformers/paraphrase-multilingual-minilm-l12-v2",
                         "thenlper/gte-large", "intfloat/multilingual-e5-large",
                         "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"}:
        return [{"kind": "pooling_update", "message":
                 f"The model {name} now uses mean pooling instead of CLS embedding. "
                 "In order to preserve the previous behaviour, consider either pinning fastembed version to 0.5.1 or "
                 "using `add_custom_model` functionality."}]
    return []


def build_catalogue(descriptions: list[dict], snapshots: dict) -> dict:
    models, seen = [], set()
    for row in descriptions:
        name, repo = row["model"], row["sources"]["hf"]
        if not isinstance(name, str) or name.lower() in seen:
            raise ValueError("distinct public model names required")
        seen.add(name.lower())
        snapshot = snapshots[repo]
        revision = snapshot["revision"]
        if not isinstance(revision, str) or not re.fullmatch("[0-9a-f]{40}", revision):
            raise ValueError("immutable repository revision required")
        artifacts = {}
        for path in [row["model_file"], *row["additional_files"], *CONFIG_FILES]:
            if path not in snapshot["artifacts"]:
                raise ValueError(f"missing registered artifact: {repo}/{path}")
            record = snapshot["artifacts"][path]
            if (type(record["bytes"]) is not int or record["bytes"] < 0
                    or not re.fullmatch("[0-9a-f]{64}", record["sha256"])):
                raise ValueError("artifact size and SHA256 required")
            artifacts[path] = {"bytes": record["bytes"], "sha256": record["sha256"]}
        if type(row["dim"]) is not int or row["dim"] <= 0:
            raise ValueError("positive registered dimension required")
        models.append({"format": "ken-fastembed-model/1", "name": name,
                       "assets": {"model_id": repo, "revision": revision,
                                  "license": row["license"], "artifacts": artifacts},
                       "graph": row["model_file"], "dimension": row["dim"],
                       "pooling": POOLING[row["implementation"]],
                       "task_id": 1 if row["implementation"] == "JinaEmbeddingV3" else None,
                       "advisories": advisories(name)})
    return {"format": "ken-fastembed-catalog/1", "models": models}
