"""Instruction frames may be removed; behavior, constraints and names remain."""
from content_query import content_query


def test_english_request_frame_does_not_contribute_behavior_words():
    assert content_query('Which function rejects empty input before decoding?') == (
        'rejects empty input before decoding?')
    assert content_query('Find the method that returns `user_id` without mutating it.') == (
        'returns `user_id` without mutating it.')


def test_spanish_frames_preserve_negation_and_sequence():
    assert content_query('¿Qué función valida sin escribir antes de devolver?') == (
        'valida sin escribir antes de devolver?')
    assert content_query('Dónde está el método que no modifica `x`') == 'no modifica `x`'


def test_instruction_words_inside_identifiers_or_behavior_are_preserved():
    assert content_query('Which function calls `class` after `where_is`?') == (
        'calls `class` after `where_is`?')
    for query in ['package.which_function', 'function_that', '`Which function`',
                  'Where should function lookup prefer a global over a method?']:
        assert content_query(query) == query


def test_underspecified_frame_does_not_become_an_empty_query():
    for query in ['Which function', 'Find the method', '¿Qué función?', 'Where is the code?']:
        assert content_query(query) == query


def test_returned_content_is_idempotent_and_keeps_language_modifiers():
    query = 'Which function returns the class definition instead of executing it?'
    content = content_query(query)
    assert content_query(content) == content
    assert content == 'returns the class definition instead of executing it?'
    # An unmodelled qualifier must not be dropped along with the requested noun.
    assert content_query('Which asynchronous function fails without awaiting?') == (
        'Which asynchronous function fails without awaiting?')
