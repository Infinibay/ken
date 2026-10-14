import hashlib
from dataclasses import replace

from ken.retrieval.model import CodeMatch, EntityKey, Passage, SearchRequest, Span
from ken.retrieval.presentation import present


def source_match(tmp_path, *, kind="function", regions=()):
    lines = ["def transform(value):"] + ["    step(value)" for _ in range(79)]
    lines[30], lines[60] = "    remove_credentials(value)", "    preserve_destination(value)"
    source = "\n".join(lines) + "\n"
    (tmp_path / "client.py").write_text(source)
    entity = EntityKey("client.py", kind, "transform")
    p = Passage(entity, Span(29, 33), {"body": "\n".join(lines[28:33]), "identity": "transform"},
                hashlib.sha256(source.encode()).hexdigest(), Span(1, 80),
                implementation_start_line=2, signals={"joint_evidence": 2.})
    second = replace(p, span=Span(59, 63), fields={**p.fields, "body": "\n".join(lines[58:63])})
    return CodeMatch(entity, 9., [p, second], p.source_hash, {}, regions)


def test_evidence_selection_compares_actual_windows_and_keeps_owner_order(tmp_path):
    from ken.retrieval.evidence import refine_evidence
    match = source_match(tmp_path)
    class Judge:
        def score(self, query, documents, *, purpose):
            assert purpose == "implementation"
            return [3. if "remove_credentials(value)" in doc and "preserve_destination(value)" in doc
                    else -1. for doc in documents]
    request = SearchRequest("remove credentials while preserving destination")
    matches = refine_evidence([match], tmp_path, request, judge=Judge())
    assert matches[0].entity == match.entity
    assert matches[0].score == match.score
    response = present(matches, tmp_path, request, profile_version="test").to_dict()
    evidence = response["results"][0]["evidence"][0]
    assert evidence["start_line"] <= 31 <= 61 <= evidence["end_line"]
    assert evidence["end_line"] - evidence["start_line"] + 1 <= 40
    assert evidence["content"] == "\n".join((tmp_path / "client.py").read_text().splitlines()[
        evidence["start_line"] - 1:evidence["end_line"]])


def test_class_evidence_cannot_borrow_code_from_child_scope(tmp_path):
    from ken.retrieval.evidence import refine_evidence
    match = source_match(tmp_path, kind="class", regions=(Span(1, 3),))
    class Judge:
        def score(self, query, documents, *, purpose):
            assert all("remove_credentials" not in doc and "preserve_destination" not in doc for doc in documents)
            return [0.] * len(documents)
    # A real class candidate's own passage is its declaration, not the child body.
    p = replace(match.evidence[0], span=Span(1, 3), fields={"body": "def transform(value):\n    step(value)\n    step(value)"})
    match = replace(match, evidence=[p])
    request = SearchRequest("remove credentials")
    refined = refine_evidence([match], tmp_path, request, judge=Judge())
    result = present(refined, tmp_path, request, profile_version="test").results[0]
    assert result["evidence"][0]["end_line"] <= 3


def test_changed_source_never_becomes_new_evidence(tmp_path):
    from ken.retrieval.evidence import refine_evidence
    match = source_match(tmp_path)
    (tmp_path / "client.py").write_text("replacement\n")
    class Judge:
        def score(self, *args, **kwargs):
            raise AssertionError("stale source must not be scored")
    request = SearchRequest("remove credentials")
    matches = refine_evidence([match], tmp_path, request, judge=Judge())
    assert present(matches, tmp_path, request, profile_version="test").results[0]["stale"]
