"""The static-table backend: a lookup and a sum instead of a transformer.

The artifact these tests build is synthetic and tiny — a five-word vocabulary
and a 2x3 table — because what needs testing is the *plumbing*: that the
tokenizer travels with the table it was fitted against, that a text maps to the
sum of its rows, that resolution prefers the table only when it is actually
present. The quality of a real fitted table is not a unit-test question; it is
measured against labelled retrieval elsewhere.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ken.embedder import STATIC_MODEL, _build_backend, is_static_model, recommended_model
from ken.embedder.static_head import StaticHeadEmbedder, artifact_available


def _tokenizer_json() -> str:
    """A word-level tokenizer, serialised the way the real artifact carries it."""
    from tokenizers import Tokenizer, models, pre_tokenizers

    vocab = {"alfa": 0, "beta": 1, "gamma": 2, "delta": 3, "[UNK]": 4}
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    return tok.to_str()


def _artifact(tmp_path, A=None, B=None):
    """A complete, loadable head. Rows are chosen so sums are checkable by eye.

    Every row is non-zero, including the ``[UNK]`` row — with an identity-shaped
    table the unknown row would be all zeros, and a test asserting that unknown
    words still produce a unit vector would be asserting something the fixture
    made impossible rather than something the code does.
    """
    A = (
        np.array(
            [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [0, 0, 2]], dtype=np.float32
        )
        if A is None
        else A
    )
    B = np.eye(3, 3, dtype=np.float32) if B is None else B
    path = tmp_path / "head.npz"
    np.savez_compressed(
        path,
        lut=np.arange(5, dtype=np.int32),
        A=A,
        B=B,
        tokenizer=np.frombuffer(_tokenizer_json().encode("utf-8"), dtype=np.uint8),
        meta=np.frombuffer(
            json.dumps({"name": "test/static", "dim": 3}).encode("utf-8"), dtype=np.uint8
        ),
    )
    return path


def test_static_model_names_are_recognised():
    assert is_static_model(STATIC_MODEL)
    assert not is_static_model("sentence-transformers/all-MiniLM-L6-v2")
    assert not is_static_model("Qwen/Qwen3-Embedding-0.6B")


def test_build_backend_routes_static_names(tmp_path, monkeypatch):
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    emb = _build_backend(STATIC_MODEL)
    assert isinstance(emb, StaticHeadEmbedder)
    assert emb.dim == 3


def test_text_encodes_to_the_normalised_sum_of_its_rows(tmp_path, monkeypatch):
    """The whole model, checked arithmetically: gather the rows, add, normalise."""
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    emb = StaticHeadEmbedder("test/static")

    (one,) = emb.embed_passages(["alfa"])
    assert one == pytest.approx([1.0, 0.0, 0.0])

    # "alfa beta" sums row 0 (1,0,0) and row 1 (0,1,0) -> normalised diagonal.
    (two,) = emb.embed_passages(["alfa beta"])
    assert two == pytest.approx([0.70710678, 0.70710678, 0.0])

    # Order cannot matter: this is a bag, and that is the whole trade.
    (rev,) = emb.embed_passages(["beta alfa"])
    assert rev == pytest.approx(two)


def test_batching_does_not_change_a_vector(tmp_path, monkeypatch):
    """A text's vector must not depend on what it was encoded alongside —
    otherwise an index built one batch size at a time is not self-consistent."""
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    emb = StaticHeadEmbedder("test/static")

    alone = emb.embed_passages(["alfa beta"])[0]
    together = emb.embed_passages(["gamma", "alfa beta", "delta gamma"])[1]
    assert alone == pytest.approx(together)


def test_queries_and_passages_share_one_table(tmp_path, monkeypatch):
    """No prompt, no second head: measured to beat both alternatives."""
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    emb = StaticHeadEmbedder("test/static")

    assert emb.embed_queries(["alfa beta"])[0] == pytest.approx(
        emb.embed_passages(["alfa beta"])[0]
    )
    assert emb.embed_query("alfa") == pytest.approx(emb.embed_passages(["alfa"])[0])


def test_unknown_words_and_empty_text_do_not_raise(tmp_path, monkeypatch):
    """ken embeds whatever the indexer found. A file with no symbols yields an
    empty text, and `np.add.reduceat` treats an empty segment as a value rather
    than a sum — the backend has to handle that rather than return a stray row."""
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    emb = StaticHeadEmbedder("test/static")

    vecs = emb.embed_passages(["", "zeta", "alfa"])
    assert np.linalg.norm(vecs[0]) == 0.0  # nothing in, nothing out
    assert np.linalg.norm(vecs[1]) == pytest.approx(1.0)  # unknown -> the UNK row
    assert vecs[2] == pytest.approx([1.0, 0.0, 0.0])
    assert emb.embed_passages([]) == []


def test_missing_artifact_names_the_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("KEN_STATIC_HEAD", str(tmp_path / "absent.npz"))
    emb = StaticHeadEmbedder("test/static")
    with pytest.raises(RuntimeError, match="KEN_STATIC_HEAD"):
        emb.embed_passages(["alfa"])


def test_a_truncated_artifact_is_rejected(tmp_path, monkeypatch):
    """A table without its tokenizer would silently become a different function,
    because the rows are indexed by that tokenizer's ids."""
    path = tmp_path / "partial.npz"
    np.savez_compressed(path, A=np.eye(5, 3, dtype=np.float32))
    monkeypatch.setenv("KEN_STATIC_HEAD", str(path))
    emb = StaticHeadEmbedder("test/static")
    with pytest.raises(RuntimeError, match="not a ken static head"):
        emb.embed_passages(["alfa"])


def test_recommended_model_prefers_the_table_only_when_present(tmp_path, monkeypatch):
    """Naming a table ken cannot find would break a fresh install, so the
    preference is conditional on the file existing."""
    monkeypatch.setenv("KEN_CONFIG_DIR", str(tmp_path / "cfg"))  # no user default
    monkeypatch.setenv("KEN_STATIC_HEAD", str(tmp_path / "absent.npz"))
    assert not artifact_available(STATIC_MODEL)
    assert recommended_model() != STATIC_MODEL

    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    assert artifact_available(STATIC_MODEL)
    assert recommended_model() == STATIC_MODEL


def test_user_default_still_wins_over_the_table(tmp_path, monkeypatch):
    monkeypatch.setenv("KEN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("KEN_STATIC_HEAD", str(_artifact(tmp_path)))
    from ken.embedder import set_user_default_model

    set_user_default_model("Qwen/Qwen3-Embedding-0.6B")
    assert recommended_model() == "Qwen/Qwen3-Embedding-0.6B"
