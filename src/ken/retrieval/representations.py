"""Build independent identity/behavior projections from the same source evidence."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

from ken.retrieval.embedding_store import put_embeddings, reclaim_embeddings
from ken.retrieval.model import Passage
from ken.retrieval.profile import Encoder, RetrievalProfile, load_encoder
from ken.retrieval.storage import load_passage_map
from ken.vectors import immediate


def passage_text(passage: Passage, view: str) -> str:
    fields = passage.fields
    if view == "identity":
        return "\n".join((fields["identity"], fields["signature"][:600], fields["path"]))
    if view == "behavior":
        return "\n".join((fields["path"], fields["identity"], fields["body"],
                          "Documentation: " + fields["documentation"][:600]))
    raise ValueError("unknown retrieval view")


def index_embeddings(conn: sqlite3.Connection, profile: RetrievalProfile, *,
                     encoders: Mapping[str, Encoder] | None = None) -> None:
    passages = load_passage_map(conn)
    if not passages:
        raise ValueError("no source passages indexed; run source indexing first")
    prepared = {}
    for view in ("identity", "behavior"):
        spec = getattr(profile, view)
        encoder = encoders[view] if encoders else load_encoder(spec)
        texts = {pid: passage_text(p, view) for pid, p in passages.items()}
        unique = list(dict.fromkeys(texts.values()))
        vectors = encoder.embed_passages(unique)
        if len(vectors) != len(unique):
            raise ValueError("encoder returned a different number of embeddings")
        by_text = dict(zip(unique, vectors, strict=True))
        prepared[view] = (texts, {pid: by_text[text] for pid, text in texts.items()})
    with immediate(conn):
        for view, (texts, vectors_by_id) in prepared.items():
            put_embeddings(conn, view, getattr(profile, view).key, texts, vectors_by_id)
        conn.execute("INSERT INTO meta(key,value) VALUES ('retrieval_profile',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (json.dumps(profile.to_dict(), sort_keys=True),))
        reclaim_embeddings(conn)
