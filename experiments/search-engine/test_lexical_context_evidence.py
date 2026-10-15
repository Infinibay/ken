"""Context quotes retain canonical owners and original physical line ranges."""
from dataclasses import replace
import hashlib

import pytest

from ken.parsers.python import parse_python_file
from ken.retrieval.model import EntityKey, Span
from ken.retrieval.passages import extract_passages
from lexical_context import build_lexical_contexts


def fixture():
    source = b'''def outer():
    def child():
        return 1
    return child
'''
    passages = extract_passages(source, parse_python_file(source, 'sample.py'), path='sample.py', language='python')
    primary = EntityKey('sample.py', 'function', 'outer')
    context = build_lexical_contexts(source, passages, path='sample.py', language='python',
        generation='snapshot7', expected_source_hash=hashlib.sha256(source).hexdigest()).contexts[primary]
    return source, context


def test_quoted_nested_source_retains_its_canonical_owner():
    from lexical_context_evidence import context_fragments
    source, context = fixture()
    quotes = context_fragments(context, source, [Span(1, 4)], primary=context.primary, generation='snapshot7')
    assert len(quotes) == 1
    assert quotes[0]['content'] == source.decode().rstrip('\n')
    assert quotes[0]['start_line'] == 1 and quotes[0]['end_line'] == 4
    assert quotes[0]['source_owners'] == [
        {'start_line': 1, 'end_line': 1, 'entity': context.primary.to_dict()},
        {'start_line': 2, 'end_line': 3, 'entity': EntityKey('sample.py', 'function', 'outer.child', 'outer').to_dict()},
        {'start_line': 4, 'end_line': 4, 'entity': context.primary.to_dict()},
    ]


def test_a_trimmed_quote_never_keeps_metadata_for_hidden_lines():
    from lexical_context_evidence import context_fragments
    source, context = fixture()
    quotes = context_fragments(context, source, [Span(3, 4)], primary=context.primary, generation='snapshot7')
    assert [(p['start_line'], p['end_line']) for p in quotes[0]['source_owners']] == [(3, 3), (4, 4)]
    assert quotes[0]['content'] == '        return 1\n    return child'


@pytest.mark.parametrize('fault', ['hash', 'generation', 'primary', 'outside', 'overlap', 'too_many'])
def test_invalid_context_selection_fails_closed(fault):
    from lexical_context_evidence import context_fragments
    source, context = fixture()
    generation, primary, spans = 'snapshot7', context.primary, [Span(1, 4)]
    if fault == 'hash': source += b'#changed\n'
    elif fault == 'generation': generation = 'other7'
    elif fault == 'primary': primary = replace(primary, definition_ordinal=1)
    elif fault == 'outside': spans = [Span(1, 5)]
    elif fault == 'overlap': spans = [Span(1, 3), Span(3, 4)]
    elif fault == 'too_many': spans = [Span(i, i) for i in range(1, 5)]
    with pytest.raises(ValueError):
        context_fragments(context, source, spans, primary=primary, generation=generation)


def test_visible_line_budget_is_the_total_of_all_selected_fragments():
    from lexical_context_evidence import context_fragments
    source, context = fixture()
    with pytest.raises(ValueError):
        context_fragments(context, source, [Span(1, 2), Span(4, 4)], primary=context.primary,
                          generation='snapshot7', max_lines=2)
