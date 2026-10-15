from ken.retrieval.model import EntityKey, Passage, Span


def test_description_separates_documentation_and_execution_across_owned_regions():
    from ken.retrieval.description import describe_owner

    entity = EntityKey('worker.py', 'function', 'work')
    shared = {'identity': 'function work', 'signature': 'def work(value):',
              'documentation': 'Describe retries.', 'path': 'worker.py'}
    passages = [
        Passage(entity, Span(1, 2), {**shared, 'body': 'def work(value):\n    """Describe retries."""'},
                'abc', Span(1, 9), implementation_start_line=3),
        Passage(entity, Span(3, 4), {**shared, 'body': '    # Retry after failure.\n    first(value)'},
                'abc', Span(1, 9), implementation_start_line=3),
        # Lines 5..7 belong to a nested function and are deliberately absent.
        Passage(entity, Span(8, 9), {**shared, 'body': '    return finish(value)\n'},
                'abc', Span(1, 9), implementation_start_line=3),
    ]
    description = describe_owner(passages)
    assert description.fields['documentation'] == 'Describe retries.'
    assert 'Describe retries' not in description.fields['implementation']
    assert 'Retry after failure' in description.fields['comments']
    assert description.fields['executable'] == '    first(value)\n    return finish(value)'
    assert description.fields['calls'] == 'first\nfinish'
    assert description.fields['returns'] == '    return finish(value)'
    assert description.owned_lines == 6
    assert description.executable_lines == 2
    assert description.comment_lines == 1


def test_owner_descriptions_reject_mixed_owners_or_source_versions():
    import pytest
    from dataclasses import replace
    from ken.retrieval.description import describe_owner

    first = Passage(EntityKey('a.py', 'function', 'a'), Span(1, 1), {'body': 'return 1'},
                    'one', Span(1, 1))
    with pytest.raises(ValueError, match='owner'):
        describe_owner([first, replace(first, entity=EntityKey('a.py', 'function', 'b'))])
    with pytest.raises(ValueError, match='source'):
        describe_owner([first, replace(first, source_hash='two')])
    with pytest.raises(ValueError, match='passages'):
        describe_owner([])
