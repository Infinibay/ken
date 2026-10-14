"""Build independent identity/behavior projections from the same source evidence."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from ken.retrieval.embedding_store import (IndexVersionError, cached_embeddings, pending_texts,
                                           put_embeddings, reclaim_embeddings, retrieval_snapshot)
from ken.retrieval.model import Passage
from ken.retrieval.profile import Encoder, RetrievalProfile, load_encoder
from ken.retrieval.storage import generation, load_passage_map
from ken.retrieval.passages import lexical_token_count
from ken.vectors import immediate


def passage_text(passage: Passage, view: str) -> str:
    fields = passage.fields
    if view == "identity":
        return "\n".join((fields["identity"], fields["signature"][:600], fields["path"]))
    if view == "behavior":
        return "\n".join((fields["path"], fields["identity"], fields["body"],
                          "Documentation: " + fields["documentation"][:600]))
    raise ValueError("unknown retrieval view")


def _prefix(text: str, budget: int, counter) -> str:
    if budget <= 0:
        return ""
    if counter(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if counter(text[:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def bounded_passage_text(passage: Passage, view: str, profile: RetrievalProfile, encoder) -> str:
    fields = passage.fields
    counter = getattr(encoder, "token_count", lexical_token_count)
    # Reserve special tokens and the longest passage prefix in the supported encoders.
    available = getattr(profile, view).sequence_length - 6
    if available < 32:
        raise ValueError("encoder sequence budget is too small for code evidence")
    header = "\n".join((fields["identity"], fields["path"], fields["signature"]))
    if view == "identity":
        return _prefix(header, min(available, 192), counter)
    if view != "behavior":
        raise ValueError("unknown retrieval view")
    body = _prefix(fields["body"], min(profile.max_tokens, available - 24), counter)
    header = _prefix(header, min(128, available - counter("\nSource:\n" + body)), counter)
    text = header + "\nSource:\n" + body
    while counter(text) > available and header:
        header = header[:-1]
        text = header + "\nSource:\n" + body
    remaining = available - counter(text + "\nDocumentation:\n")
    documentation = _prefix(fields["documentation"], min(64, remaining), counter)
    if documentation:
        text += "\nDocumentation:\n" + documentation
    if counter(text) > available:
        raise ValueError("projection exceeds its actual tokenizer budget")
    return text


def index_embeddings(conn: sqlite3.Connection, profile: RetrievalProfile, *,
                     encoders: Mapping[str, Encoder] | None = None) -> None:
    with retrieval_snapshot(conn) as snapshot:
        passages = load_passage_map(conn)
        source_generation = snapshot.generation
    if not passages:
        raise ValueError("no source passages indexed; run source indexing first")
    prepared = {}
    for view in ("identity", "behavior"):
        spec = getattr(profile, view)
        encoder = encoders[view] if encoders else load_encoder(spec)
        texts = {pid: bounded_passage_text(p, view, profile, encoder) for pid, p in passages.items()}
        texts = pending_texts(conn, view, profile.vector_revision(view), texts)
        if not texts:
            continue
        unique = list(dict.fromkeys(texts.values()))
        by_text = cached_embeddings(conn, view, profile.vector_revision(view), unique)
        missing = [text for text in unique if text not in by_text]
        vectors = encoder.embed_passages(missing) if missing else []
        if len(vectors) != len(missing):
            raise ValueError("encoder returned a different number of embeddings")
        by_text.update(zip(missing, vectors, strict=True))
        prepared[view] = (texts, {pid: by_text[text] for pid, text in texts.items()})
    with immediate(conn):
        if generation(conn) != source_generation:
            raise IndexVersionError("source changed while encoding; retry indexing")
        for view, (texts, vectors_by_id) in prepared.items():
            put_embeddings(conn, view, profile.vector_revision(view), texts, vectors_by_id)
        conn.execute("INSERT INTO meta(key,value) VALUES ('retrieval_profile',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (json.dumps(profile.to_dict(), sort_keys=True),))
        if prepared:
            reclaim_embeddings(conn)
        conn.execute("INSERT INTO meta(key,value) VALUES ('retrieval_representation_version',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(profile.representation_version),))
