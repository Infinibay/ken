"""Indexer pipeline: hash, unchanged-skip, parse, persist, delete."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.indexer import _hash, _is_unchanged, delete_file, delete_path, index_files


class _FakeEmbedder:
    """Deterministic stand-in for the real embedder. Same shape, no model load."""

    @property
    def dim(self) -> int:
        return 384

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)

    def _vec(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) & 0xFFFF_FFFF)
        v = rng.normal(size=384).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)


@pytest.fixture
def project(tmp_path):
    """Project root with a real on-disk SQLite DB and the schema applied."""
    root = tmp_path
    (root / ".ken").mkdir()
    db = root / ".ken" / "ken.db"
    conn = connect(db)
    init_schema(conn)
    yield root, conn
    conn.close()


def test_hash_is_deterministic():
    h1 = _hash(b"hello world")
    h2 = _hash(b"hello world")
    h3 = _hash(b"hello mars")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 32  # blake2b-256


def test_index_files_skips_too_large(project):
    root, conn = project
    big = root / "big.py"
    big.write_bytes(b"x = 1\n" * 200_000)  # > 1 MB
    stats = index_files(conn, root, [Path("big.py")], max_file_bytes=1024)
    assert stats.skipped_too_large == 1
    assert stats.parsed == 0


def test_index_files_persists_symbols_and_imports(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text(
        '''import os
def foo():
    """Doc."""
    return 1
'''
    )
    stats = index_files(conn, root, [Path("mod.py")])
    assert stats.parsed == 1
    assert stats.symbols == 1
    assert stats.imports == 1
    rows = conn.execute("SELECT name FROM ci_symbols").fetchall()
    assert rows[0]["name"] == "foo"


def test_index_files_resolves_internal_python_import(project):
    root, conn = project
    (root / "pkg").mkdir()
    (root / "pkg" / "util.py").write_text("def helper(): return 1\n")
    (root / "main.py").write_text("import pkg.util\n")

    index_files(conn, root, [Path("pkg/util.py"), Path("main.py")])

    row = conn.execute(
        """
        SELECT f.path AS target
        FROM ci_imports i
        JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.to_module = 'pkg.util'
        """
    ).fetchone()
    assert row["target"] == "pkg/util.py"


def test_index_files_skips_unchanged_on_rerun(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])
    stats2 = index_files(conn, root, [Path("mod.py")])
    assert stats2.unchanged == 1
    assert stats2.parsed == 0


def test_is_unchanged_requires_embedding_when_asked(project):
    """Indexed without embedder, then queried with need_embedding=True
    should return False so the daemon's warm pass picks it up."""
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])  # no embedder → no embedding
    content_hash = _hash(src.read_bytes())
    assert _is_unchanged(conn, "mod.py", content_hash, need_embedding=False) is True
    assert _is_unchanged(conn, "mod.py", content_hash, need_embedding=True) is False


def test_index_files_with_embedder_populates_embedding(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")], embedder=_FakeEmbedder())
    row = conn.execute(
        "SELECT embedding IS NOT NULL AS has_emb FROM ci_files WHERE path = 'mod.py'"
    ).fetchone()
    assert row["has_emb"] == 1


def test_delete_file_cascades_to_symbols(project):
    root, conn = project
    src = root / "mod.py"
    src.write_text("def x(): return 1\n")
    index_files(conn, root, [Path("mod.py")])
    assert delete_file(conn, "mod.py") is True
    sym_count = conn.execute("SELECT COUNT(*) FROM ci_symbols").fetchone()[0]
    assert sym_count == 0


def test_delete_file_returns_false_when_missing(project):
    _, conn = project
    assert delete_file(conn, "nope.py") is False


def test_delete_path_removes_indexed_subtree(project):
    root, conn = project
    kept = root / "pkg_extra.py"
    wildcard_neighbor = root / "pkgA" / "nested.py"
    nested = root / "pkg" / "nested.py"
    nested.parent.mkdir()
    wildcard_neighbor.parent.mkdir()
    kept.write_text("def kept(): return 1\n")
    wildcard_neighbor.write_text("def neighbor(): return 3\n")
    nested.write_text("def nested(): return 2\n")
    index_files(
        conn,
        root,
        [Path("pkg_extra.py"), Path("pkgA/nested.py"), Path("pkg/nested.py")],
    )

    assert delete_path(conn, "pkg") == 1

    rows = conn.execute("SELECT path FROM ci_files ORDER BY path").fetchall()
    assert [row["path"] for row in rows] == ["pkgA/nested.py", "pkg_extra.py"]
