"""Build source boundaries and embeddings under one explicit retrieval profile."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ken.retrieval.embedding_store import IndexVersionError, put_embeddings
from ken.retrieval.model import Passage
from ken.retrieval.passages import EXTRACTOR_VERSION, PassagePolicy
from ken.retrieval.profile import Encoder, RetrievalProfile, active_profile, load_encoder


def _stored_profile(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    values = dict(conn.execute("SELECT key,value FROM meta WHERE key IN "
        "('retrieval_profile','retrieval_profile_fingerprint')"))
    return values.get("retrieval_profile"), values.get("retrieval_profile_fingerprint")


@dataclass(frozen=True)
class PreparedProjection:
    """Both encoded views for one file, ready for its source transaction."""
    profile: RetrievalProfile
    expected_profile: tuple[str | None, str | None]
    views: Mapping[str, tuple[list[str], list[np.ndarray]]]

    def publish(self, conn: sqlite3.Connection, passage_ids: list[int]) -> None:
        if _stored_profile(conn) != self.expected_profile:
            raise IndexVersionError("retrieval profile changed while encoding; retry indexing")
        for view, (texts, vectors) in self.views.items():
            if len(passage_ids) != len(texts):
                raise ValueError("source and prepared projection lengths differ")
            put_embeddings(conn, view, self.profile.vector_revision(view),
                dict(zip(passage_ids, texts, strict=True)), dict(zip(passage_ids, vectors, strict=True)))


class ProjectionIndexer:
    """Prepare changed-file views outside writes under a single profile."""
    def __init__(self, conn: sqlite3.Connection, profile: RetrievalProfile, *,
                 encoders: Mapping[str, Encoder] | None = None):
        self.conn = conn
        self.profile = profile
        self.expected_profile = _stored_profile(conn)
        self.encoders = dict(encoders or {})

    @classmethod
    def for_active(cls, conn: sqlite3.Connection, *,
                   encoders: Mapping[str, Encoder] | None = None) -> ProjectionIndexer | None:
        stored, fingerprint = _stored_profile(conn)
        if stored is None:
            return None
        profile = active_profile(conn)
        if fingerprint != profile.fingerprint:
            raise IndexVersionError("retrieval runtime or projection changed; reindex the retrieval profile")
        return cls(conn, profile, encoders=encoders)

    def encoder(self, view: str) -> Encoder:
        if view not in self.encoders:
            self.encoders[view] = load_encoder(getattr(self.profile, view))
        return self.encoders[view]

    def token_count(self, text: str) -> int:
        counter = getattr(self.encoder("behavior"), "token_count", None)
        if counter is None:
            raise ValueError("behavior-model segmentation requires its actual tokenizer")
        return counter(text)

    @property
    def policy(self) -> PassagePolicy:
        if self.profile.passage_tokenizer == "code-lexical-v1":
            return PassagePolicy(max_tokens=self.profile.max_tokens)
        # The counter is lazy: unchanged files need neither weights nor tokenizer.
        return PassagePolicy(self.profile.max_tokens, self.token_count, source_policy_key(self.profile)[1])

    def prepare(self, files: list[list[Passage]]) -> list[PreparedProjection]:
        from ken.retrieval.representations import bounded_passage_text, encode_texts
        flat = [p for passages in files for p in passages]
        views = {}
        for view in ("identity", "behavior"):
            encoder = self.encoder(view)
            texts = [bounded_passage_text(p, view, self.profile, encoder) for p in flat]
            by_text = encode_texts(self.conn, view, self.profile.vector_revision(view), texts, encoder)
            views[view] = (texts, [by_text[text] for text in texts])
        prepared, start = [], 0
        for passages in files:
            end = start + len(passages)
            prepared.append(PreparedProjection(self.profile, self.expected_profile,
                {view: (texts[start:end], vectors[start:end]) for view, (texts, vectors) in views.items()}))
            start = end
        return prepared


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
                 else f"{spec.model_id}@{spec.revision}:tokenizer-v1:{spec.tokenizer_revision}")
    return EXTRACTOR_VERSION, tokenizer, profile.max_tokens


def index_project(conn: sqlite3.Connection, root: Path, files: Iterable[Path], *,
                   profile: RetrievalProfile, encoders: Mapping[str, Encoder] | None = None):
    from ken.indexer import index_files
    from ken.retrieval.representations import index_embeddings
    stats = index_files(conn, root, files, retrieval_profile=profile, retrieval_encoders=encoders)
    index_embeddings(conn, profile, encoders=encoders)
    return stats
