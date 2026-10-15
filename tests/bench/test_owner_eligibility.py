"""Training relevance requires source capable of satisfying the original target."""
from ken.retrieval.model import EntityKey, Span


def alternative(entity=None, *, anchors=((3, 5), (10, 11))):
    return {'path': 'auth.py', 'entity': entity, 'source_hash': 'a' * 64,
            'anchors': [Span(*bounds).to_dict() for bounds in anchors]}


def test_file_fragment_does_not_label_every_owner_in_that_file_positive():
    from ken.bench.owner_eligibility import eligible_owner
    entity = EntityKey('auth.py', 'function', 'other')
    assert not eligible_owner(entity, 'a' * 64, (Span(20, 30),), [alternative()])
    assert not eligible_owner(entity, 'a' * 64, (Span(3, 5),), [alternative()])
    assert eligible_owner(entity, 'a' * 64, (Span(3, 5), Span(10, 11)), [alternative()])


def test_named_owner_and_source_hash_are_both_required():
    from ken.bench.owner_eligibility import eligible_owner
    owner = EntityKey('auth.py', 'method', 'Client.clear', 'Client', 1)
    expected = alternative(owner.to_dict())
    assert eligible_owner(owner, 'a' * 64, (Span(1, 20),), [expected])
    assert not eligible_owner(owner, 'b' * 64, (Span(1, 20),), [expected])
    assert not eligible_owner(EntityKey('auth.py', 'method', 'Client.clear', 'Client'),
                              'a' * 64, (Span(1, 20),), [expected])


def test_all_lines_of_one_alternative_must_be_available_without_gap_filling():
    from ken.bench.owner_eligibility import eligible_owner
    owner = EntityKey('auth.py', 'function', 'clear')
    assert not eligible_owner(owner, 'a' * 64, (Span(3, 4), Span(10, 11)), [alternative()])
    assert not eligible_owner(owner, 'a' * 64, (Span(3, 5), Span(10, 11)),
                              [alternative(anchors=((3, 10),))])
    assert eligible_owner(owner, 'a' * 64, (Span(3, 4), Span(5, 5)),
                          [alternative(), alternative(anchors=((3, 5),))])
