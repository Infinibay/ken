"""Fixed lexical projection; caller supplies the existing coverage calculation."""
import hashlib

import numpy as np

from ken.parsers.python import parse_python_file
from ken.retrieval.model import EntityKey
from ken.retrieval.passages import extract_passages
from lexical_context import build_lexical_contexts


def fixture():
    source = b'''def outer():
    def child():
        def grandchild():
            return "once"
        return grandchild
    return child
'''
    passages = extract_passages(source, parse_python_file(source, 'sample.py'), path='sample.py', language='python')
    return build_lexical_contexts(source, passages, path='sample.py', language='python',
        generation='snapshot7', expected_source_hash=hashlib.sha256(source).hexdigest()).contexts[
            EntityKey('sample.py', 'function', 'outer')]


def test_projection_retains_literal_nested_code_once_and_excludes_no_source_owner():
    from lexical_context_features import context_texts
    context = fixture()
    fields = context_texts(context)
    assert fields['lexical_full'] == context.text
    assert fields['lexical_nested'].count('return "once"') == 1
    assert 'return grandchild' in fields['lexical_nested']
    assert 'return child' not in fields['lexical_nested']
    assert 'def child' in fields['lexical_nested']


def test_fixed_summaries_use_existing_coverage_and_keep_absence_neutral():
    from lexical_context_features import FEATURES, lexical_context_features, STATS, FIELDS
    context = fixture()
    calls = []
    def coverage(query, documents, fields):
        calls.append((query, documents, fields))
        return [{f'{field}_{stat}': float(j+1) for j, (field, stat) in enumerate(
            (f,s) for f in FIELDS for s in STATS)} for _ in documents]
    values = lexical_context_features('public expanded query', [context, None], coverage=coverage)
    assert values.shape == (2, len(FEATURES)) == (2, 25)
    assert np.array_equal(values[0,:20], np.arange(1,21))
    assert np.array_equal(values[1], np.zeros(25))
    assert values[0,20] == 1
    assert 0 < values[0,-1] <= 1
    assert calls[0][0] == 'public expanded query'
    assert calls[0][2] == FIELDS
    assert set(calls[0][1][0]) == {*FIELDS, 'all'}


def test_an_empty_context_batch_does_not_call_the_encoder():
    from lexical_context_features import lexical_context_features
    def forbidden(*args):
        raise AssertionError('no context needs no coverage model call')
    assert lexical_context_features('query', [None, None], coverage=forbidden).shape == (2, 25)
