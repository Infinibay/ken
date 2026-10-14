from pathlib import Path
import json

import numpy as np

from ken.db import connect, init_schema
from ken.indexer import index_files


class Encoder:
    def embed_passages(self, texts):
        return [np.array([1.0, 0.0] if "authorization" in t.lower() else [0.0, 1.0],
                         dtype=np.float32) for t in texts]

    def embed_query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


def setup(tmp_path):
    from ken.retrieval.profile import EncoderSpec, RetrievalProfile
    from ken.retrieval.representations import index_embeddings
    source = "def redirect(headers):\n" + "    x = 1\n" * 80 + "    headers.pop('Authorization', None)\n"
    (tmp_path / "client.py").write_text(source)
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("client.py")])
    spec = EncoderSpec("test/encoder", "a" * 40, "provided")
    profile = RetrievalProfile(spec, spec)
    encoders = {"identity": Encoder(), "behavior": Encoder()}
    index_embeddings(conn, profile, encoders=encoders)
    return conn, profile, encoders


def test_late_anchor_is_visible_with_faithful_ranges_and_budget(tmp_path):
    from ken.retrieval.service import search
    from ken.retrieval.model import SearchRequest
    conn, profile, encoders = setup(tmp_path)
    response = search(conn, tmp_path, SearchRequest("Where is Authorization removed?"),
                      profile=profile, encoders=encoders).to_dict()
    first = response["results"][0]
    assert first["entity"]["qualname"] == "redirect"
    assert any("headers.pop" in e["content"] for e in first["evidence"])
    lines = (tmp_path / "client.py").read_text().splitlines()
    for e in first["evidence"]:
        assert e["content"] == "\n".join(lines[e["start_line"]-1:e["end_line"]])
    assert sum(e["end_line"] - e["start_line"] + 1 for e in first["evidence"]) <= 40
    assert len(json.dumps(response, ensure_ascii=False, separators=(",", ":"))) <= 12000
    conn.close()


def test_budget_does_not_reorder_matches_or_invent_partial_lines(tmp_path):
    from ken.retrieval.service import search
    from ken.retrieval.model import SearchRequest
    conn, profile, encoders = setup(tmp_path)
    response = search(conn, tmp_path, SearchRequest("redirect", max_chars=900),
                      profile=profile, encoders=encoders).to_dict()
    assert len(json.dumps(response, ensure_ascii=False, separators=(",", ":"))) <= 900
    assert response["results"][0]["entity"]["qualname"] == "redirect"
    for fragment in response["results"][0]["evidence"]:
        assert fragment["end_line"] - fragment["start_line"] + 1 == len(fragment["content"].splitlines())
    conn.close()


def test_concurrent_edit_marks_stale_and_never_quotes_old_source(tmp_path):
    from ken.retrieval.service import search
    from ken.retrieval.model import SearchRequest
    conn, profile, encoders = setup(tmp_path)
    (tmp_path / "client.py").write_text("def replacement():\n    return 'changed'\n")
    response = search(conn, tmp_path, SearchRequest("redirect"),
                      profile=profile, encoders=encoders).to_dict()
    assert response["results"][0]["stale"]
    assert response["results"][0]["evidence"] == []
    assert response["warnings"]
    conn.close()


def test_file_search_exposes_matching_member_not_first_eight(tmp_path):
    from ken.retrieval.service import search
    from ken.retrieval.model import SearchRequest
    conn, profile, encoders = setup(tmp_path)
    response = search(conn, tmp_path, SearchRequest("redirect", target="file"),
                      profile=profile, encoders=encoders).to_dict()
    assert response["results"][0]["matches"][0]["qualname"] == "redirect"
    conn.close()


def test_budget_trimming_preserves_trailing_blank_source_lines(tmp_path):
    import hashlib
    from ken.retrieval.model import CodeMatch, EntityKey, Passage, SearchRequest, Span
    from ken.retrieval.presentation import present
    source = b"\n\n\n"
    (tmp_path / "blank.txt").write_bytes(source)
    entity = EntityKey("blank.txt", "module", None)
    passage = Passage(entity, Span(1, 3), {"body": "\n\n"},
                      hashlib.sha256(source).hexdigest(), Span(1, 3))
    result = present([CodeMatch(entity, 1, [passage], passage.source_hash)], tmp_path,
                     SearchRequest("source", max_chars=300), profile_version="test").to_dict()
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 300


def test_behavior_evidence_does_not_spend_line_budget_on_a_long_docstring(tmp_path):
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.service import search
    source = 'def normalize(value):\n    """Normalize the value.\n' + (
        '    Normalize the value and preserve invalid values.\n' * 80
    ) + '    """\n    if value is None:\n        return "missing"\n    return value.strip().lower()\n'
    (tmp_path / "normalize.py").write_text(source)
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("normalize.py")])
    first = search(conn, tmp_path, SearchRequest("normalize")).to_dict()["results"][0]
    visible = {line for e in first["evidence"] for line in range(e["start_line"], e["end_line"] + 1)}
    assert {84, 85, 86} <= visible
