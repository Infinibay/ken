"""Independent retrieval channels vote once per canonical source owner."""
from copy import deepcopy

import pytest

from ken.retrieval.model import Candidate, EntityKey, Passage, Span


def candidate(name, **signals):
    owner = EntityKey('client.py', 'function', name)
    p = Passage(owner, Span(2, 4), {'body': 'return 1'}, 'a' * 64, Span(2, 4),
                signals={key: value for key, value in signals.items()})
    return Candidate(owner, [p], signals, (p.span,))


def test_fusion_preserves_channel_measurements_and_does_not_mutate_inputs():
    from ken.retrieval.proposals import fuse_proposals
    first = candidate('save', bm25f=3., cosine_behavior=.4)
    second = candidate('save', cosine_behavior=.8)
    channels = {'original': [first], 'translated': [second]}
    before = deepcopy(channels)
    result = fuse_proposals(channels, limit=100)
    assert channels == before
    assert len(result) == 1
    assert result[0].signals['bm25f'] == 3.
    assert result[0].signals['cosine_behavior'] == .8
    assert result[0].signals['rrf'] == pytest.approx(2 / 61)
    assert result[0].passages[0].signals['cosine_behavior'] == .8
    assert result[0].owned_regions == (Span(2, 4),)


def test_duplicate_owner_in_one_channel_has_only_one_vote():
    from ken.retrieval.proposals import fuse_proposals
    first = candidate('save')
    result = fuse_proposals({'identity': [first, first], 'behavior': [candidate('load')]}, limit=2)
    assert {c.signals['rrf'] for c in result} == {1 / 61}


def test_exact_target_survives_the_final_owner_budget():
    from ken.retrieval.proposals import fuse_proposals
    exact = candidate('save', exact=1.)
    result = fuse_proposals({'one': [candidate('load'), exact],
                             'two': [candidate('load')]}, limit=1)
    assert [c.entity.qualname for c in result] == ['save']


def test_fusion_rejects_mixed_source_generations():
    from dataclasses import replace
    from ken.retrieval.proposals import fuse_proposals
    first = candidate('save')
    other = candidate('save')
    other.passages = [replace(other.passages[0], source_hash='b' * 64)]
    with pytest.raises(ValueError, match='source'):
        fuse_proposals({'one': [first], 'two': [other]}, limit=100)


def test_different_owners_from_the_same_file_must_share_its_source_version():
    from dataclasses import replace
    from ken.retrieval.proposals import fuse_proposals
    first = candidate('save')
    other = candidate('load')
    other.passages = [replace(other.passages[0], source_hash='b' * 64)]
    with pytest.raises(ValueError, match='source'):
        fuse_proposals({'one': [first], 'two': [other]}, limit=100)
