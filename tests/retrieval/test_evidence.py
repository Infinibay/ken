import hashlib
from dataclasses import replace

import pytest

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


@pytest.mark.parametrize("kind", ["class", "function"])
def test_owner_evidence_cannot_borrow_code_from_child_scope(tmp_path, kind):
    from ken.retrieval.evidence import refine_evidence
    match = source_match(tmp_path, kind=kind, regions=(Span(1, 3),))
    class Judge:
        def score(self, query, documents, *, purpose):
            assert all("remove_credentials" not in doc and "preserve_destination" not in doc for doc in documents)
            return [0.] * len(documents)
    # The parent's own declaration is separate from its nested callable body.
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


def test_distant_decisive_blocks_use_separate_faithful_fragments_with_one_total_budget(tmp_path):
    from ken.retrieval.evidence import refine_evidence
    match = source_match(tmp_path)
    lines = (tmp_path / "client.py").read_text().splitlines() + ["    step(value)"] * 80
    lines[60], lines[140] = "    step(value)", "    preserve_destination(value)"
    source = "\n".join(lines) + "\n"
    (tmp_path / "client.py").write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    first = replace(match.evidence[0], source_hash=digest, entity_span=Span(1, 160))
    second = replace(first, span=Span(139, 143), fields={**first.fields, "body": "\n".join(lines[138:143])})
    match = replace(match, evidence=[first, second], source_hash=digest)
    class Judge:
        def score(self, query, documents, *, purpose):
            return [3. if "remove_credentials(value)" in doc and "preserve_destination(value)" in doc
                    else -1. for doc in documents]
    request = SearchRequest("remove credentials while preserving destination")
    refined = refine_evidence([match], tmp_path, request, judge=Judge())
    evidence = present(refined, tmp_path, request, profile_version="test").results[0]["evidence"]
    visible = {n for e in evidence for n in range(e["start_line"], e["end_line"]+1)}
    assert {31, 141} <= visible
    assert sum(e["end_line"]-e["start_line"]+1 for e in evidence) <= 40
    assert len(evidence) == 2
    for e in evidence:
        assert e["content"] == "\n".join(lines[e["start_line"]-1:e["end_line"]])


def test_source_coverage_uses_the_expanded_query_and_can_split_a_long_passage(tmp_path):
    from ken.retrieval.source_evidence import refine_source_evidence

    lines = ['def store():', '    validate(cookie)'] + ['    step(value)']*97 + ['    persist(cookie)']
    source = '\n'.join(lines)+'\n'; (tmp_path/'client.py').write_text(source)
    match = source_match(tmp_path)
    # Restore the source after the fixture has written its own example.
    (tmp_path/'client.py').write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    p = replace(match.evidence[0], span=Span(2,100), entity_span=Span(1,100),
        source_hash=digest, fields={'body':'\n'.join(lines[1:])})
    match = replace(match,evidence=[p],source_hash=digest,owned_regions=(Span(1,100),))
    request = SearchRequest('validar y guardar la cookie')
    refined = refine_source_evidence([match],tmp_path,request,query='validate and persist cookie',
                                    stem_words=lambda words: words)
    evidence = present(refined,tmp_path,request,profile_version='test').results[0]['evidence']
    visible = {n for e in evidence for n in range(e['start_line'],e['end_line']+1)}
    assert {2,100} <= visible
    assert len(evidence) == 2
    assert sum(e['end_line']-e['start_line']+1 for e in evidence) <= 40


def test_unique_exact_name_keeps_the_declaration_visible_for_a_long_function(tmp_path):
    match = source_match(tmp_path)
    lines = (tmp_path/'client.py').read_text().splitlines()
    first = replace(match.evidence[0],span=Span(1,20),fields={'body':'\n'.join(lines[:20])})
    match = replace(match,evidence=[first,*match.evidence],signals={'exact':1.})
    response = present([match],tmp_path,SearchRequest('transform'),profile_version='test')
    assert response.results[0]['evidence'][0]['start_line'] == 1


def test_source_coverage_cannot_fill_a_parent_gap_with_child_evidence(tmp_path):
    from ken.retrieval.source_evidence import refine_source_evidence
    match = source_match(tmp_path,kind='class',regions=(Span(1,3),))
    lines = (tmp_path/'client.py').read_text().splitlines()
    p = replace(match.evidence[0],span=Span(1,3),fields={'body':'\n'.join(lines[:3])})
    match = replace(match,evidence=[p])
    request = SearchRequest('remove credentials while preserving destination')
    refined = refine_source_evidence([match],tmp_path,request,query=request.query,
                                    stem_words=lambda words:words)
    evidence = present(refined,tmp_path,request,profile_version='test').results[0]['evidence']
    assert all(f['end_line'] <= 3 for f in evidence)


def test_exact_identity_respects_a_preselected_fragments_total_budget(tmp_path):
    lines = ['def store(', '    value,', '):']+['    step(value)']*97
    source = '\n'.join(lines)+'\n'; (tmp_path/'client.py').write_text(source)
    entity = EntityKey('client.py','function','store')
    digest = hashlib.sha256(source.encode()).hexdigest()
    evidence = [Passage(entity,span,{'body':'\n'.join(lines[span.start_line-1:span.end_line]),
        'signature':'\n'.join(lines[:3])},digest,Span(1,100),signals={'selected_window':1.})
        for span in (Span(10,29),Span(80,99))]
    match = CodeMatch(entity,1.,evidence,digest,{'exact':1.})
    result = present([match],tmp_path,SearchRequest('store'),profile_version='test').results[0]
    assert not result['stale']
    assert sum(p['end_line']-p['start_line']+1 for p in result['evidence']) == 40
