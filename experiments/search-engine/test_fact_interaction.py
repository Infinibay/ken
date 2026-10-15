import numpy as np
import pytest


def test_clause_boundaries_preserve_quotes_conditions_and_explicit_alternatives():
    from fact_interaction import query_clauses
    required, avoided = query_clauses('Where are "and before" tokens kept when valid and returned instead of throwing, but errors stay visible?')
    assert required == ('Where are "and before" tokens kept', 'when valid', 'returned', 'errors stay visible?')
    assert avoided == ('throwing',)


def test_without_remains_context_and_does_not_claim_operation_absence():
    from fact_interaction import query_clauses
    assert query_clauses('Find parsing without a final newline') == (('Find parsing', 'without a final newline'), ())


def test_each_required_clause_must_find_a_fact_in_the_same_owner():
    from fact_interaction import fact_features
    original = expanded = np.array([1., 0.], np.float32)
    required = np.eye(2, dtype=np.float32)
    empty = np.empty((0, 2), np.float32)
    one = fact_features(original, expanded, required, empty, required[:1], ['value_relations'])
    both = fact_features(original, expanded, required, empty, required, ['value_relations']*2)
    # union metrics are full-original/full-expanded/required-min/required-mean/alternative-max
    np.testing.assert_array_equal(one[25:30], [1., 1., 0., .5, 0.])
    np.testing.assert_array_equal(both[25:30], [1., 1., 1., 1., 0.])


def test_alternative_match_stays_separate_from_required_support():
    from fact_interaction import fact_features
    q = np.array([1., 0.], np.float32)
    result = fact_features(q, q, q[None, :], np.array([[0., 1.]], np.float32), np.eye(2, dtype=np.float32), ['conditions','value_relations'])
    np.testing.assert_array_equal(result[25:30], [1., 1., 1., 1., 1.])
    assert result[-1] == 1.


def test_empty_source_is_preserved_with_zero_evidence():
    from fact_interaction import fact_features
    q = np.array([1., 0.], np.float32)
    empty = np.empty((0, 2), np.float32)
    np.testing.assert_array_equal(fact_features(q, q, q[None,:], empty, empty, []), np.zeros(32))


def test_nonfinite_fact_vectors_are_rejected():
    from fact_interaction import fact_features
    q = np.array([1., 0.], np.float32)
    with pytest.raises(ValueError, match='finite'):
        fact_features(q, q, q[None,:], np.empty((0,2),np.float32), np.full((1,2),np.nan), ['conditions'])


def test_escaped_backtick_remains_inside_the_quoted_literal():
    from fact_interaction import query_clauses
    assert query_clauses(r'Find `a\` and b` and return') == ((r'Find `a\` and b`', 'return'), ())


def test_english_contractions_do_not_hide_clause_boundaries():
    from fact_interaction import query_clauses
    assert query_clauses("Find values that don't mutate and don't disappear") == (("Find values that don't mutate", "don't disappear"), ())
