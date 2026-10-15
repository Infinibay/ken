"""Lexical name context has provenance and keeps homonyms unresolved."""
from ken.retrieval.model import EntityKey, Passage, Span
from name_context import declaration_name, mentioned_names


def passage(text, start=1):
    entity = EntityKey('source.py', 'function', 'caller')
    span = Span(start, start+len(text.splitlines())-1)
    return Passage(entity, span, {'body': text}, 'test-hash', span)


def test_name_projection_preserves_case_and_common_language_qualifiers():
    assert declaration_name(EntityKey('a.py', 'method', 'C.helper')) == 'helper'
    assert declaration_name(EntityKey('a.rs', 'method', 'Regex::find')) == 'find'
    assert declaration_name(EntityKey('a.js', 'function', '$run')) == '$run'
    assert declaration_name(EntityKey('a.py', 'module', None)) is None


def test_postings_use_whole_names_and_actual_passage_line_numbers():
    source = passage('foobar()\nfoo()\nbar()\nfoo()', start=11)
    assert mentioned_names([source], frozenset({'foo', 'bar'})) == (('bar', 13), ('foo', 12))


def test_strings_comments_and_definitions_are_lexical_mentions_not_calls():
    source = passage('def foo():\n    # bar is described here\n    return "baz"')
    assert mentioned_names([source], frozenset({'foo', 'bar', 'baz'})) == (
        ('bar', 2), ('baz', 3), ('foo', 1))


def test_a_mention_cannot_choose_between_global_and_class_homonyms():
    global_name = declaration_name(EntityKey('a.py', 'function', 'helper'))
    class_name = declaration_name(EntityKey('a.py', 'method', 'C.helper'))
    assert global_name == class_name == 'helper'
    assert mentioned_names([passage('return helper()')], frozenset({global_name})) == (
        ('helper', 1),)


def test_dollar_and_unicode_names_are_kept_without_case_folding_or_bridging_holes():
    first = passage('$run(); Δείγμα(); Foo()', start=4)
    last = passage('foo()', start=12)
    assert mentioned_names([last, first], frozenset({'$run', 'Δείγμα', 'foo'})) == (
        ('$run', 4), ('foo', 12), ('Δείγμα', 4))
