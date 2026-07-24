"""Query-vs-passage encoding and cross-model vector-space safety.

Asymmetric embedding models (``intfloat/e5-*``, ``Qwen/Qwen3-Embedding-*``)
encode a *question* and a *stored document* differently — the query side gets
a task-instruction prefix. Every vector ken persists therefore has a fixed
role, and writing it through the wrong method files it in a space nothing
searches. The symmetric default models make such a mix-up invisible, so these
tests use a deliberately asymmetric double.

Roles:

* documents — ``ci_files``, ``ci_symbols``, ``ci_intent_sources``, ``cr_findings``
* queries   — ``cr_contexts`` (user prompts, compared against a live prompt)
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.embedder import (
    EmbeddingSpaceMismatch,
    cosine_against,
    stack_embeddings,
    vec_to_blob,
)
from ken.indexer import index_files
from ken.memory import recall, remember
from ken.reembed import reembed

_DIM = 4


class AsymmetricEmbedder:
    """Puts queries and passages in provably different subspaces.

    Slot 0 is 1.0 for a passage and 0.0 for a query, so a vector's origin can
    be read straight off the stored blob.
    """

    model_name = "fake/asymmetric"

    def __init__(self) -> None:
        self.passage_texts: list[str] = []
        self.query_texts: list[str] = []

    @property
    def dim(self) -> int:
        return _DIM

    def _body(self, text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) & 0xFFFF)
        return rng.random(_DIM - 1).astype(np.float32)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        self.passage_texts.extend(texts)
        return [np.concatenate(([1.0], self._body(t))).astype(np.float32) for t in texts]

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        self.query_texts.extend(texts)
        return [np.concatenate(([0.0], self._body(t))).astype(np.float32) for t in texts]

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_queries([text])[0]


def _is_passage(blob: bytes) -> bool:
    return float(np.frombuffer(bytes(blob), dtype=np.float32)[0]) == 1.0


@pytest.fixture()
def conn(tmp_path):
    (tmp_path / ".ken").mkdir()
    c = connect(tmp_path / ".ken" / "ken.db")
    init_schema(c)
    yield c
    c.close()


# ── indexer: everything it stores is a document ──────────────────────


def test_indexer_stores_documents_as_passages(conn, tmp_path):
    (tmp_path / "mod.py").write_text(
        '"""Module purpose line."""\n\n'
        'def parse(text):\n    """Parse the text."""\n    return text\n',
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("release checklist\n", encoding="utf-8")
    emb = AsymmetricEmbedder()
    index_files(conn, tmp_path, [Path("mod.py"), Path("notes.txt")], embedder=emb)

    files = conn.execute(
        "SELECT path, embedding FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchall()
    assert {r["path"] for r in files} == {"mod.py", "notes.txt"}
    for row in files:
        assert _is_passage(row["embedding"]), f"{row['path']} was encoded as a query"

    for table in ("ci_symbols", "ci_intent_sources"):
        rows = conn.execute(
            f"SELECT embedding FROM {table} WHERE embedding IS NOT NULL"
        ).fetchall()
        assert rows, table
        assert all(_is_passage(r["embedding"]) for r in rows), table

    assert emb.query_texts == []


# ── findings: stored as documents, searched with a query ─────────────


def test_findings_are_stored_as_passages_and_recalled_with_a_query(conn, monkeypatch):
    emb = AsymmetricEmbedder()
    monkeypatch.setattr("ken.memory.get_embedder", lambda: emb)

    assert remember(conn, "codex wiring", "Use --codex to repair hooks.")["ok"]
    stored = conn.execute("SELECT embedding FROM cr_findings").fetchone()["embedding"]
    assert _is_passage(stored)
    assert emb.query_texts == []

    recall(conn, "codex", limit=3, min_score=None)
    assert emb.query_texts == ["codex"]


# ── reembed: preserves each column's role ────────────────────────────


def test_reembed_keeps_prompts_in_query_space(conn, monkeypatch):
    now_ms = int(time.time() * 1000)
    zero = vec_to_blob(np.zeros(_DIM, dtype=np.float32))
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES ('src/a.py','python',?,?,?,?)",
        (b"\x00" * 32, now_ms, now_ms, zero),
    )
    conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, "
        "docstring, embedding) VALUES (1,'function','go','go',1,2,'does things',?)",
        (zero,),
    )
    conn.execute("INSERT INTO cr_sessions(agent_id, started_at) VALUES ('a', ?)", (now_ms,))
    conn.execute(
        "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
        "VALUES (1,'user_prompt','fix the thing',0,?,?)",
        (zero, now_ms),
    )
    conn.execute(
        "INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at) "
        "VALUES ('t','c','[]',?,?,?)",
        (zero, now_ms, now_ms),
    )
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: AsymmetricEmbedder())
    reembed(conn)

    # A user prompt is compared against a freshly embedded prompt — both sides
    # are queries, so re-encoding it as a passage would strand it.
    prompt = conn.execute("SELECT embedding FROM cr_contexts").fetchone()["embedding"]
    assert not _is_passage(prompt)

    for table in ("ci_files", "ci_symbols", "cr_findings"):
        blob = conn.execute(f"SELECT embedding FROM {table}").fetchone()["embedding"]
        assert _is_passage(blob), table


def test_indexer_and_reembed_agree_on_the_file_vector_space(conn, tmp_path):
    """An incremental re-index after a reembed must not write another space."""
    (tmp_path / "mod.py").write_text("def parse(text):\n    return text\n", encoding="utf-8")
    index_files(conn, tmp_path, [Path("mod.py")], embedder=AsymmetricEmbedder())
    indexed = conn.execute("SELECT embedding FROM ci_files").fetchone()["embedding"]

    import ken.reembed as reembed_mod

    original = reembed_mod.get_embedder
    reembed_mod.get_embedder = lambda: AsymmetricEmbedder()
    try:
        reembed(conn)
    finally:
        reembed_mod.get_embedder = original
    reembedded = conn.execute("SELECT embedding FROM ci_files").fetchone()["embedding"]

    assert _is_passage(indexed) == _is_passage(reembedded)


# ── cross-model vector-space guards ──────────────────────────────────


def test_stack_embeddings_drops_rows_from_another_model():
    blobs = [
        vec_to_blob(np.ones(4, dtype=np.float32)),
        vec_to_blob(np.ones(8, dtype=np.float32)),  # written by an older model
        vec_to_blob(np.ones(4, dtype=np.float32)),
    ]
    mat, kept = stack_embeddings(blobs, dim=4)
    assert kept == [0, 2]
    assert mat.shape == (2, 4)


def test_stack_embeddings_raises_when_the_whole_index_is_stale():
    blobs = [vec_to_blob(np.ones(8, dtype=np.float32))]
    with pytest.raises(EmbeddingSpaceMismatch, match="ken reembed"):
        stack_embeddings(blobs, dim=4)


def test_cosine_against_normalises_stored_rows():
    q = np.array([3.0, 4.0], dtype=np.float32)  # deliberately not unit length
    mat = np.array([[6.0, 8.0], [-3.0, -4.0]], dtype=np.float32)
    sims = cosine_against(q, mat)
    assert sims[0] == pytest.approx(1.0, abs=1e-5)
    assert sims[1] == pytest.approx(-1.0, abs=1e-5)


def test_recall_skips_findings_written_by_another_model(conn, monkeypatch):
    emb = AsymmetricEmbedder()
    monkeypatch.setattr("ken.memory.get_embedder", lambda: emb)
    remember(conn, "current", "encoded by the live model")

    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at) "
        "VALUES ('stale','from an older model','[]',?,?,?)",
        (vec_to_blob(np.ones(16, dtype=np.float32)), now_ms, now_ms),
    )
    hits = recall(conn, "anything", limit=5, min_score=None)
    assert [h["topic"] for h in hits] == ["current"]


# ── prompt policy is shared by both backends ─────────────────────────


def test_prompt_policy_covers_the_asymmetric_models():
    from ken.embedder import is_asymmetric, prompts_for

    assert prompts_for("intfloat/multilingual-e5-large") == ("query: ", "passage: ")
    assert prompts_for("Qwen/Qwen3-Embedding-0.6B")[0].startswith("Instruct:")
    assert prompts_for("Qwen/Qwen3-Embedding-0.6B")[1] == ""
    assert is_asymmetric("intfloat/e5-base") is True
    # The shipped defaults are symmetric — the fix must be a no-op for them.
    assert prompts_for("sentence-transformers/all-MiniLM-L6-v2") == ("", "")
    assert is_asymmetric(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ) is False


def test_onnx_backend_applies_the_query_passage_prompts(monkeypatch):
    # e5 is served by fastembed, whose own query_embed/passage_embed are plain
    # aliases of embed for every model but Jina — so ken has to prefix, or the
    # asymmetry is never applied on the default backend.
    from ken.embedder import is_asymmetric
    from ken.embedder.onnx_fastembed import OnnxEmbedder

    assert is_asymmetric("intfloat/multilingual-e5-large")
    seen: list[list[str]] = []

    class _Model:
        def embed(self, texts):
            seen.append(list(texts))
            return [np.zeros(4, dtype=np.float32) for _ in texts]

    emb = OnnxEmbedder("intfloat/multilingual-e5-large")
    monkeypatch.setattr(emb, "_ensure_model", lambda: _Model())

    emb.embed_passages(["a file", "another"])
    emb.embed_query("a question")
    emb.embed_queries(["q1", "q2"])

    assert seen[0] == ["passage: a file", "passage: another"]
    assert seen[1] == ["query: a question"]
    assert seen[2] == ["query: q1", "query: q2"]


def test_onnx_backend_leaves_symmetric_models_untouched(monkeypatch):
    from ken.embedder.onnx_fastembed import OnnxEmbedder

    seen: list[list[str]] = []

    class _Model:
        def embed(self, texts):
            seen.append(list(texts))
            return [np.zeros(4, dtype=np.float32) for _ in texts]

    emb = OnnxEmbedder("sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setattr(emb, "_ensure_model", lambda: _Model())
    emb.embed_passages(["x"])
    emb.embed_query("x")
    assert seen == [["x"], ["x"]]


# ── stale document space is detected and surfaced ────────────────────


def test_pending_reembed_fires_only_for_a_stale_asymmetric_index(conn):
    from ken.db import set_meta
    from ken.embedder import (
        DOC_SPACE_VERSION,
        META_DOC_SPACE,
        META_EMBED_MODEL,
        pending_reembed,
        record_doc_space,
    )

    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES ('a.py','python',?,?,?,?)",
        (b"\x00" * 32, now_ms, now_ms, vec_to_blob(np.ones(4, dtype=np.float32))),
    )

    # Asymmetric model, no marker -> the index predates the split.
    set_meta(conn, META_EMBED_MODEL, "intfloat/multilingual-e5-large")
    reason = pending_reembed(conn)
    assert reason is not None and "e5" in reason

    # Once reembedded, it stops nagging.
    record_doc_space(conn)
    assert pending_reembed(conn) is None

    # A symmetric model encodes documents and queries identically, so there is
    # nothing to migrate however old the marker is.
    set_meta(conn, META_DOC_SPACE, "1")
    set_meta(conn, META_EMBED_MODEL, "sentence-transformers/all-MiniLM-L6-v2")
    assert pending_reembed(conn) is None
    assert DOC_SPACE_VERSION >= 2


def test_session_brief_tells_the_user_to_reembed(conn):
    from ken.db import set_meta
    from ken.embedder import META_EMBED_MODEL
    from ken.session_brief import build_session_brief

    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES ('a.py','python',?,?,?,?)",
        (b"\x00" * 32, now_ms, now_ms, vec_to_blob(np.ones(4, dtype=np.float32))),
    )
    set_meta(conn, META_EMBED_MODEL, "Qwen/Qwen3-Embedding-0.6B")

    brief = build_session_brief(conn, now_ms=now_ms)
    assert "ken reembed" in brief
    # Throttled: it must not repeat on the very next session.
    assert "ken reembed" not in build_session_brief(conn, now_ms=now_ms + 1000)


# ── background scorers degrade instead of raising ────────────────────


def test_ranker_channels_survive_a_stale_dimension(conn):
    # search/recall raise (the user asked and is waiting); the ranker runs
    # inside a hook, where raising costs the user their context injection.
    from ken.ranker.channels import _fuzzy_files

    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES ('a.py','python',?,?,?,?)",
        (b"\x00" * 32, now_ms, now_ms, vec_to_blob(np.ones(16, dtype=np.float32))),
    )
    assert _fuzzy_files(conn, np.ones(4, dtype=np.float32)) == []


def test_rank_against_keeps_rows_aligned_with_scores():
    from ken.embedder import rank_against

    blobs = [
        vec_to_blob(np.array([1.0, 0.0], dtype=np.float32)),
        vec_to_blob(np.ones(9, dtype=np.float32)),  # older model
        vec_to_blob(np.array([0.0, 1.0], dtype=np.float32)),
    ]
    sims, kept = rank_against(np.array([1.0, 0.0], dtype=np.float32), blobs, strict=False)
    assert kept == [0, 2]
    assert len(sims) == 2
    assert sims[0] == pytest.approx(1.0, abs=1e-6)
    assert sims[1] == pytest.approx(0.0, abs=1e-6)
