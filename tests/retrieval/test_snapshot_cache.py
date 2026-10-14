from pathlib import Path

import numpy as np

from ken.db import connect, init_schema
from ken.indexer import index_files
from ken.retrieval.candidates import retrieve
from ken.retrieval.model import SearchRequest
from ken.retrieval.representations import index_embeddings
from tests.retrieval.test_candidates import Encoder, profile


def test_warm_query_reuses_immutable_vectors_but_writer_invalidates(tmp_path, monkeypatch):
    import ken.retrieval.candidates as candidates
    source = tmp_path / "client.py"
    source.write_text("def cookie():\n    return 'cookie'\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("client.py")])
    encoders = {"identity": Encoder(), "behavior": Encoder()}
    index_embeddings(conn, profile(), encoders=encoders)
    loads = []
    original = candidates.load_vectors
    def counted(*args):
        loads.append(args[1])
        return original(*args)
    monkeypatch.setattr(candidates, "load_vectors", counted)
    for _ in range(2):
        retrieve(conn, tmp_path, SearchRequest("browser state"), profile(), encoders=encoders)
    assert loads == ["identity", "behavior"]
    source.write_text("def cookie():\n    return 'new cookie'\n")
    index_files(conn, tmp_path, [Path("client.py")])
    index_embeddings(conn, profile(), encoders=encoders)
    result = retrieve(conn, tmp_path, SearchRequest("browser state"), profile(), encoders=encoders)
    assert loads == ["identity", "behavior", "identity", "behavior"]
    assert any("new cookie" in p.fields["body"] for p in result[0].passages)
    import hashlib
    assert all(p.source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
               for p in result[0].passages)


def test_cache_never_shares_rows_between_databases(tmp_path):
    encoders = {"identity": Encoder(), "behavior": Encoder()}
    for index, name in enumerate(("first", "second")):
        root = tmp_path / name
        root.mkdir()
        (root / "client.py").write_text(f"def {name}():\n    return 'cookie'\n")
        conn = connect(root / "index.db")
        init_schema(conn)
        index_files(conn, root, [Path("client.py")])
        index_embeddings(conn, profile(), encoders=encoders)
        result = retrieve(conn, root, SearchRequest("browser state"), profile(), encoders=encoders)
        assert result[0].entity.qualname == name
