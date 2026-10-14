from dataclasses import replace

import numpy as np

from ken.retrieval.model import Candidate, EntityKey, Passage, SearchRequest, Span


def candidate(name, body, role="definition"):
    entity = EntityKey("source.py", "function", name)
    p = Passage(entity, Span(1, 3), {"body": body, "identity": name, "signature": name,
        "documentation": "", "path": "source.py"}, "a" * 64, Span(1, 3), role=role)
    return Candidate(entity, [p], {"rrf": 1})


def test_joint_ranker_orders_behavior_and_never_counts_duplicate_passages_as_votes():
    from ken.retrieval.ranking import rank_candidates
    wrong = candidate("clear", "return value")
    wrong.passages *= 20
    right = candidate("redirect", "headers.pop('Authorization', None)")
    class Judge:
        def score(self, query, documents, *, purpose):
            assert len(documents) == 2
            assert documents[0].count("return value") == 1
            return np.array([-2., 3.])
    matches = rank_candidates(SearchRequest("remove credentials on redirect"),
                              [wrong, right], judge=Judge())
    assert matches[0].entity.qualname == "redirect"
    assert matches[0].score == 3
    assert matches[0].signals["joint_relevance"] == 3


def test_test_purpose_reaches_joint_ranker_and_exact_identity_stays_first():
    from ken.retrieval.ranking import rank_candidates
    exact = candidate("Client.redirect", "implementation")
    exact.signals["exact"] = 1
    test = candidate("test_redirect", "assert credentials_removed", role="test")
    class Judge:
        def score(self, query, documents, *, purpose):
            assert purpose == "tests"
            return [-3, 8]
    matches = rank_candidates(SearchRequest("Which test verifies redirects?"), [exact, test], judge=Judge())
    assert matches[0].entity == exact.entity


def test_joint_ranker_rejects_nonfinite_scores():
    import pytest
    from ken.retrieval.ranking import rank_candidates
    class Judge:
        def score(self, *args, **kwargs):
            return [float("nan")]
    with pytest.raises(ValueError, match="finite"):
        rank_candidates(SearchRequest("credentials"), [candidate("redirect", "body")], judge=Judge())


def test_last_real_token_projection_equals_full_vocabulary_logits():
    import torch
    from ken.retrieval.joint_model import project_last_token
    hidden = torch.tensor([[[1., 2.], [3., 4.], [99., 99.]], [[2., 3.], [4., 5.], [6., 7.]]])
    mask = torch.tensor([[1, 1, 0], [1, 1, 1]])
    weights = torch.tensor([[1., 0.], [2., 1.], [-1., 3.], [0., -2.]])
    expected = (hidden @ weights.T)[[0, 1], [1, 2], 2] - (hidden @ weights.T)[[0, 1], [1, 2], 1]
    assert torch.allclose(project_last_token(hidden, mask, weights, true_id=2, false_id=1), expected)


def test_validation_repository_cannot_fit_scaler_or_weights():
    import pytest
    from ken.retrieval.linear import Preference, fit_ranker
    training = [Preference("train", {"cosine_behavior": .9}, {"cosine_behavior": .1})]
    artifact = fit_ranker(training, validation_groups={"validation"}, regularization=.1)
    assert artifact.training_groups == ("train",)
    assert max(artifact.means) <= .5
    with pytest.raises(ValueError, match="overlap"):
        fit_ranker(training, validation_groups={"train"}, regularization=.1)


def test_linear_score_trace_reconstructs_rank_and_serializes():
    from ken.retrieval.linear import LinearRanker, Preference, fit_ranker
    artifact = fit_ranker([Preference("train", {"cosine_behavior": .9},
                                      {"cosine_behavior": .1})], validation_groups=set(), regularization=.1)
    features = {"cosine_behavior": .8}
    trace = artifact.explain(features)
    assert np.isclose(sum(trace.values()), artifact.score(features))
    recovered = LinearRanker.from_dict(artifact.to_dict())
    assert recovered.score(features) == artifact.score(features)


def test_implementation_comparison_does_not_treat_description_as_executable_source():
    from ken.retrieval.ranking import candidate_document
    described = candidate("Error", '"""Raised when credentials are removed."""')
    described.passages[0] = replace(described.passages[0], implementation_start_line=10)
    document = candidate_document(described, purpose="implementation")
    assert 'Raised when credentials' not in document
    assert 'no owned executable source' in document
    assert 'Raised when credentials' in candidate_document(described, purpose="documentation")


def test_passage_judgments_choose_owner_and_retain_decisive_evidence_score():
    from ken.retrieval.ranking import rank_candidates
    wrong = candidate("wrong", "return unrelated")
    wrong.passages *= 20
    right = candidate("right", "return unrelated")
    right.passages.append(replace(right.passages[0], span=Span(5, 7),
                                  fields={**right.passages[0].fields, "body": "remove_credentials()"}))
    class Judge:
        def score(self, query, documents, *, purpose):
            assert len(documents) == 3
            return [2. if "remove_credentials" in doc else -1. for doc in documents]
    matches = rank_candidates(SearchRequest("remove credentials"), [wrong, right],
                              judge=Judge(), rank_unit="passage")
    assert matches[0].entity.qualname == "right"
    best = max(matches[0].evidence, key=lambda p: p.signals["joint_evidence"])
    assert best.span == Span(5, 7)
    assert matches[0].score == 2


def test_many_reviewed_negatives_do_not_give_one_query_extra_training_weight():
    from ken.retrieval.linear import Preference, fit_ranker
    first = Preference("train", {"role_match": 1.}, {"role_match": 0.}, query_id="a")
    second = Preference("train", {"cosine_behavior": .9}, {"cosine_behavior": .1}, query_id="b")
    control = fit_ranker([first, second], validation_groups=set())
    repeated = fit_ranker([first] * 10 + [second], validation_groups=set())
    assert np.allclose(control.weights, repeated.weights, atol=1e-7)
    assert np.allclose(control.means, repeated.means, atol=1e-7)
    assert np.allclose(control.scales, repeated.scales, atol=1e-7)


def test_joint_calibrator_learns_role_compatibility_without_losing_exact_precedence():
    from ken.retrieval.linear import JOINT_FEATURES, Preference, fit_ranker
    from ken.retrieval.ranking import rank_candidates
    model = fit_ranker([Preference("train", {"joint_relevance": 7., "role_match": 1.},
        {"joint_relevance": 8., "role_match": 0.}, query_id="q")], validation_groups={"held-out"},
        features=JOINT_FEATURES)
    implementation = candidate("lookup", "raise Error")
    test = candidate("test_lookup", "assert raises(Error)", role="test")
    class Judge:
        def score(self, query, documents, *, purpose):
            return [7., 8.]
    matches = rank_candidates(SearchRequest("convert missing key to error"), [implementation, test],
                              judge=Judge(), calibrator=model)
    assert matches[0].entity == implementation.entity
    assert matches[0].signals["joint_relevance"] == 7.
    assert "calibrated_relevance" in matches[0].signals
