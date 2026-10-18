"""Saved findings retain their project vector space after a default-model change."""
from __future__ import annotations

import json

import numpy as np
import pytest

import ken.embedder as embedder
from ken import _paths
from ken.cli import main
from ken.db import connect, get_meta, init_schema, set_meta


class _SpaceEncoder:
    """Replace model inference only; keep resolution, persistence and search real."""
    def __init__(self, model):
        self.model_name = model
        self.vector = np.array({
            "test/old": [1.0, 0.0],
            "test/new-same-dimension": [0.0, 1.0],
            "test/new-different-dimension": [0.0, 1.0, 0.0],
        }[model], dtype=np.float32)
        self.dim = len(self.vector)

    def embed_passages(self, texts):
        return [self.vector.copy() for _ in texts]

    def embed_queries(self, texts):
        return self.embed_passages(texts)

    def embed_query(self, text):
        return self.vector.copy()


@pytest.fixture(params=["test/new-same-dimension", "test/new-different-dimension"])
def old_project(tmp_path, monkeypatch, request):
    root = tmp_path / "project"
    _paths.ken_dir(root).mkdir(parents=True)
    _paths.meta_path(root).write_text("{}")
    with connect(_paths.db_path(root)) as conn:
        init_schema(conn)
        set_meta(conn, "embed_model", "test/old")
        conn.execute("INSERT INTO cr_findings(topic,content,tags,embedding,created_at,updated_at) "
                     "VALUES('existing','Preserve the stored setting contract.','[]',?,1,1)",
                     (np.array([1.0, 0.0], dtype=np.float32).tobytes(),))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("KEN_EMBED_MODEL", raising=False)
    monkeypatch.setattr(embedder, "_build_backend", _SpaceEncoder)
    embedder.reset_embedder()
    embedder.set_user_default_model(request.param)
    # A process may already have loaded its default before receiving this DB.
    embedder.get_embedder()
    yield root
    embedder.reset_embedder()


def test_recall_with_explicit_path_uses_the_stored_model(old_project, capsys):
    assert main(["recall", "setting contract", "--path", str(old_project), "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["topic"] == "existing"
    assert hits[0]["score"] == 1.0
    with connect(_paths.db_path(old_project)) as conn:
        assert get_meta(conn, "embed_model") == "test/old"
        stored = conn.execute("SELECT embedding FROM cr_findings WHERE topic='existing'").fetchone()[0]
    np.testing.assert_array_equal(np.frombuffer(stored, dtype=np.float32), [1.0, 0.0])


def test_remember_with_explicit_path_does_not_mix_vector_spaces(old_project, capsys):
    assert main(["remember", "new", "Another stored setting contract.",
                 "--path", str(old_project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    with connect(_paths.db_path(old_project)) as conn:
        assert get_meta(conn, "embed_model") == "test/old"
        rows = conn.execute("SELECT embedding FROM cr_findings ORDER BY id").fetchall()
    assert len(rows) == 2
    for row in rows:
        np.testing.assert_array_equal(np.frombuffer(row[0], dtype=np.float32), [1.0, 0.0])
