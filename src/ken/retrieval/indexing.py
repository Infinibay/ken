"""Build source boundaries and embeddings under one explicit retrieval profile."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ken.retrieval.passages import EXTRACTOR_VERSION, PassagePolicy
from ken.retrieval.profile import Encoder, RetrievalProfile, load_encoder


def passage_policy(profile: RetrievalProfile, *, encoder: Any = None) -> PassagePolicy:
    if profile.passage_tokenizer == "code-lexical-v1":
        return PassagePolicy(max_tokens=profile.max_tokens)
    encoder = encoder or load_encoder(profile.behavior)
    counter = getattr(encoder, "token_count", None)
    if counter is None:
        raise ValueError("behavior-model segmentation requires its actual tokenizer")
    return PassagePolicy(profile.max_tokens, counter,
                          source_policy_key(profile)[1])


def source_policy_key(profile: RetrievalProfile) -> tuple[int, str, int]:
    spec = profile.behavior
    tokenizer = ("code-lexical-v1" if profile.passage_tokenizer == "code-lexical-v1"
                 else f"{spec.model_id}@{spec.revision}:tokenizer-v1")
    return EXTRACTOR_VERSION, tokenizer, profile.max_tokens


def index_project(conn: sqlite3.Connection, root: Path, files: Iterable[Path], *,
                   profile: RetrievalProfile, encoders: Mapping[str, Encoder] | None = None):
    from ken.indexer import index_files
    from ken.retrieval.representations import index_embeddings
    stats = index_files(conn, root, files, retrieval_policy=passage_policy(profile,
                       encoder=encoders["behavior"] if encoders else None))
    index_embeddings(conn, profile, encoders=encoders)
    return stats
