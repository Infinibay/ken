"""Immutable embedding artifacts published in the existing SQLite/WAL lifecycle."""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from ken.retrieval.storage import generation


class IndexVersionError(ValueError):
    """An explicit profile cannot be served by the stored embedding revision."""


@dataclass(frozen=True)
class VectorView:
    ids: tuple[int, ...]
    matrix: np.ndarray
    model_revision: str


@dataclass(frozen=True)
class RetrievalSnapshot:
    generation: int


@contextmanager
def retrieval_snapshot(conn: sqlite3.Connection) -> Iterator[RetrievalSnapshot]:
    """Rows and vectors share one MVCC snapshot, including concurrent reclamation.

    Like other Ken connection users, callers serialize a shared connection or
    give each concurrent request its own connection. No mapped slot is reused.
    The savepoint preserves a caller's surrounding transaction.
    """
    name = "retrieval_" + uuid.uuid4().hex
    conn.execute("SAVEPOINT " + name)
    try:
        yield RetrievalSnapshot(generation(conn))
    finally:
        conn.execute("RELEASE SAVEPOINT " + name)


def put_embeddings(conn: sqlite3.Connection, view: str, model_revision: str,
                   texts: Mapping[int, str], vectors: Mapping[int, np.ndarray]) -> None:
    if not conn.in_transaction:
        raise ValueError("embedding publication requires a transaction")
    if view not in ("identity", "behavior") or not model_revision:
        raise ValueError("view and immutable model revision required")
    if texts.keys() != vectors.keys():
        raise ValueError("embedding text/vector ids differ")
    prepared: list[tuple[int, str, np.ndarray]] = []
    dimension = None
    for pid, vector in vectors.items():
        array = np.asarray(vector, dtype=np.float32)
        if array.ndim != 1 or not array.size or not np.isfinite(array).all():
            raise ValueError("embedding must be a finite, nonempty vector")
        norm = float(np.linalg.norm(array))
        if norm <= 0:
            raise ValueError("embedding must have a positive norm")
        if dimension is not None and array.size != dimension:
            raise ValueError("mixed embedding dimensions")
        dimension = array.size
        if not conn.execute("SELECT 1 FROM ci_passages WHERE id=?", (pid,)).fetchone():
            raise IndexVersionError("source changed while encoding; reindex the retrieval profile")
        prepared.append((pid, hashlib.sha256(texts[pid].encode()).hexdigest(), array / norm))
    prior = conn.execute(
        "SELECT DISTINCT dimension FROM ci_retrieval_embeddings WHERE view=? AND model_revision=?",
        (view, model_revision),
    ).fetchall()
    if dimension is not None and any(r[0] != dimension for r in prior):
        raise IndexVersionError("model dimension changed; reindex with an immutable revision")
    for pid, text_hash, array in prepared:
        conn.execute(
            "INSERT INTO ci_retrieval_embeddings(view,model_revision,text_hash,dimension,embedding) "
            "VALUES (?,?,?,?,?) ON CONFLICT(view,model_revision,text_hash) DO NOTHING",
            (view, model_revision, text_hash, int(array.size), array.tobytes()),
        )
        artifact = conn.execute(
            "SELECT id FROM ci_retrieval_embeddings WHERE view=? AND model_revision=? AND text_hash=?",
            (view, model_revision, text_hash),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO ci_passage_vectors(passage_id,view,embedding_id) VALUES (?,?,?) "
            "ON CONFLICT(passage_id,view) DO UPDATE SET embedding_id=excluded.embedding_id",
            (pid, view, artifact),
        )
    if prepared:
        conn.execute("INSERT INTO meta(key,value) VALUES ('retrieval_generation','1') "
                     "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")


def load_vectors(conn: sqlite3.Connection, view: str, model_revision: str) -> VectorView:
    rows = conn.execute(
        "SELECT v.passage_id,e.* FROM ci_passage_vectors v "
        "JOIN ci_retrieval_embeddings e ON e.id=v.embedding_id WHERE v.view=? "
        "ORDER BY v.passage_id", (view,),
    ).fetchall()
    if any(row["model_revision"] != model_revision for row in rows):
        raise IndexVersionError(f"{view} model revision mismatch; reindex the retrieval profile")
    ids = tuple(int(row["passage_id"]) for row in rows)
    if rows:
        if len({row["dimension"] for row in rows}) != 1:
            raise IndexVersionError("mixed vector dimensions; reindex the retrieval profile")
        matrix = np.stack([np.frombuffer(row["embedding"], dtype=np.float32) for row in rows])
        if matrix.shape[1] != rows[0]["dimension"] or not np.isfinite(matrix).all():
            raise IndexVersionError("invalid embedding bytes; reindex the retrieval profile")
    else:
        matrix = np.empty((0, 0), dtype=np.float32)
    matrix.setflags(write=False)
    return VectorView(ids, matrix, model_revision)


def reclaim_embeddings(conn: sqlite3.Connection) -> int:
    """Delete unreferenced artifacts; WAL keeps prior readers' versions alive."""
    if not conn.in_transaction:
        raise ValueError("reclamation requires a transaction")
    cur = conn.execute("DELETE FROM ci_retrieval_embeddings WHERE NOT EXISTS "
                       "(SELECT 1 FROM ci_passage_vectors v "
                       "WHERE v.embedding_id=ci_retrieval_embeddings.id)")
    return cur.rowcount
