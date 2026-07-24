"""Doc-intent integration: purpose text can route prompts to code."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ken.db import connect, init_schema
from ken.embedder import embed_intent_text
from ken.indexer import index_files
from ken.ranker import rank


class SemanticDocEmbedder:
    """Tiny semantic fake: related phrases share a vector, names/paths do not."""

    @property
    def dim(self) -> int:
        return 384

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed_query(text) for text in texts]

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed_passages(texts)

    def embed_query(self, text: str) -> np.ndarray:
        lower = text.lower()
        if "filesystem" in lower and ("batch" in lower or "change" in lower):
            return _basis(0)
        if "authenticate" in lower and "session" in lower:
            return _basis(1)
        return _basis(20)


def _basis(idx: int) -> np.ndarray:
    vec = np.zeros(384, dtype=np.float32)
    vec[idx] = 1.0
    return vec


def _project(tmp_path: Path):
    (tmp_path / ".ken").mkdir()
    conn = connect(tmp_path / ".ken" / "ken.db")
    init_schema(conn)
    return conn


def test_rank_finds_file_by_module_docstring_without_path_or_symbol(tmp_path):
    conn = _project(tmp_path)
    try:
        src = tmp_path / "src" / "worker.py"
        src.parent.mkdir()
        src.write_text(
            '''"""Coordinate background filesystem change batches."""

def run():
    return 1
''',
            encoding="utf-8",
        )
        embedder = SemanticDocEmbedder()
        index_files(conn, tmp_path, [Path("src/worker.py")], embedder=embedder)
        conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('agent', ?)",
            (int(time.time() * 1000),),
        )

        result = rank(
            conn,
            agent_id="agent",
            current_iteration=1,
            prompt="How should background file change batches be coordinated?",
            prompt_embedding=embedder.embed_query("filesystem batch coordination"),
        )

        assert result.files[0].target == "src/worker.py"
        assert "doc-intent:module_docstring" in result.files[0].reason
        assert "src/worker.py" not in result.files[0].reason
    finally:
        conn.close()


def test_rank_finds_symbol_by_symbol_docstring_without_name(tmp_path):
    conn = _project(tmp_path)
    try:
        src = tmp_path / "src" / "worker.py"
        src.parent.mkdir()
        src.write_text(
            '''def perform():
    """Authenticate browser sessions for returning users."""
    return 1
''',
            encoding="utf-8",
        )
        embedder = SemanticDocEmbedder()
        index_files(conn, tmp_path, [Path("src/worker.py")], embedder=embedder)
        conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('agent', ?)",
            (int(time.time() * 1000),),
        )

        result = rank(
            conn,
            agent_id="agent",
            current_iteration=1,
            prompt="Where is returning-user browser login handled?",
            prompt_embedding=embedder.embed_query(
                embed_intent_text(
                    "symbol_docstring",
                    "Authenticate browser sessions for returning users.",
                )
            ),
        )

        assert result.symbols[0].target == "perform (src/worker.py:1)"
        assert result.files[0].target == "src/worker.py"
        assert "doc-intent-symbol:symbol_docstring" in result.files[0].reason
    finally:
        conn.close()
