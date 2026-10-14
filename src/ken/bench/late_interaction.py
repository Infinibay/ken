"""Development-only token interaction controls; no production model selection."""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np


def _matrix(value: np.ndarray) -> np.ndarray:
    matrix = np.asarray(value, dtype=np.float32)
    if matrix.ndim != 2 or not all(matrix.shape) or not np.isfinite(matrix).all():
        raise ValueError('finite, nonempty token matrix required')
    return matrix


def maxsim(query: np.ndarray, document: np.ndarray) -> float:
    """Sum one best document-token match for each query token, including negatives."""
    query, document = _matrix(query), _matrix(document)
    if query.shape[1] != document.shape[1]:
        raise ValueError('token vector dimension mismatch')
    return float((query @ document.T).max(axis=1).sum())


class DocumentVectors:
    """Content-addressed document representations; never stores query answers."""
    def __init__(self, path: Path, revision: str,
                 encode: Callable[[list[str]], Sequence[np.ndarray]]):
        self.conn = sqlite3.connect(path)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS documents('
                          'revision TEXT, digest TEXT, rows INTEGER, dims INTEGER, vector BLOB, '
                          'PRIMARY KEY(revision,digest))')
        self.revision, self.encode = revision, encode
        self.misses = 0

    def __enter__(self) -> DocumentVectors:
        return self

    def __exit__(self, *args: object) -> None:
        self.conn.close()

    def count(self) -> int:
        return int(self.conn.execute('SELECT COUNT(*) FROM documents WHERE revision=?',
                                    (self.revision,)).fetchone()[0])

    def get_many(self, texts: list[str]) -> list[np.ndarray]:
        keys = {text: hashlib.sha256(text.encode()).hexdigest() for text in texts}
        found: dict[str, np.ndarray] = {}
        missing = []
        for text, digest in keys.items():
            row = self.conn.execute('SELECT rows,dims,vector FROM documents WHERE revision=? AND digest=?',
                                    (self.revision, digest)).fetchone()
            if row:
                found[text] = _matrix(np.frombuffer(row[2], dtype='<f4').reshape(row[0], row[1]))
            else:
                missing.append(text)
        if missing:
            encoded = list(self.encode(missing))
            if len(encoded) != len(missing):
                raise ValueError('one token matrix required per document')
            matrices = [_matrix(value) for value in encoded]
            with self.conn:
                for text, matrix in zip(missing, matrices, strict=True):
                    self.conn.execute('INSERT INTO documents VALUES(?,?,?,?,?)',
                        (self.revision, keys[text], *matrix.shape, matrix.astype('<f4').tobytes()))
                    found[text] = matrix
            self.misses += len(missing)
        return [found[text] for text in texts]


def prepare_features(tokenizer, texts: list[str], *, prefix_id: int, length: int, query: bool):
    """PyLate prefix at position one; expansion tokens stay masked in attention."""
    import torch
    features = tokenizer([text.strip() for text in texts], padding='max_length' if query else True,
                         truncation=True, max_length=length-1, return_tensors='pt')
    for name, value in list(features.items()):
        marker = prefix_id if name == 'input_ids' else int(name == 'attention_mask')
        inserted = torch.full((len(texts), 1), marker, dtype=value.dtype)
        features[name] = torch.cat([value[:, :1], inserted, value[:, 1:]], dim=1)
    return features
