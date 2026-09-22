"""``return $replica copies $state;`` — the returned object carries a copied field.

The legacy catalogue stated this pattern through four relations the flow analysis
publishes (``RETURN_FIELD_STATE`` / ``FIELD_STATE_ORIGIN`` / ``FIELD_STATE_WRITE``
plus the assignment's value).  This is the KQL 2 spelling of the same claim: the
returned place is a fresh instance of the pattern's type, and one of its fields is
the receiver's field of the same name.  Which write survives aliases and branches is
the flow analysis' decision, not the query's.
"""
from __future__ import annotations

from ken.kql2.service import search


def query(claim: str) -> str:
    """The claim: a method returns a fresh instance that copied one field."""
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $state { static: false; } field $spare { } '
            'method $clone { constructor: false; body { '
            f'{claim} '
            '} } } select $unit; }')


CLAIM = 'let $replica = construct $unit {}; return $replica copies $state;'

FIXTURE = ('class Product:\n'
           ' def __init__(self):\n'
           '  self.count = 0\n'
           '  self.spare = 0\n'
           ' def copy(self):\n'
           '{body}\n')


def run(tmp_path, body: str, claim: str = CLAIM):
    (tmp_path / 'a.py').write_text(FIXTURE.format(body=body))
    return search(tmp_path, query(claim), cache_mb=0)


COPY = '  p = Product()\n  p.count = self.count\n  return p'


def test_copies_modifier_accepts_a_same_named_field_copy(tmp_path):
    result = run(tmp_path, COPY)
    assert result['complete'] and len(result['rows']) == 1, result


def test_copies_modifier_rejects_a_constant_write(tmp_path):
    # ``p.count = 1`` leaves no copied field: the returned instance holds no state
    # from the receiver.
    result = run(tmp_path, '  p = Product()\n  p.count = 1\n  return p')
    assert result['complete'] and result['rows'] == [], result


def test_copies_modifier_rejects_a_different_source_field(tmp_path):
    # The value read must be the receiver's field of the *same* name.
    result = run(tmp_path, '  p = Product()\n  p.count = self.spare\n  return p')
    assert result['complete'] and result['rows'] == [], result


def test_copies_modifier_rejects_a_different_destination_field(tmp_path):
    result = run(tmp_path, '  p = Product()\n  p.spare = self.count\n  return p')
    assert result['complete'] and result['rows'] == [], result


def test_copies_modifier_rejects_a_superseded_copy(tmp_path):
    # The last write to the field wins: a second, non-copying write means the
    # returned instance no longer retains the receiver's state.
    result = run(tmp_path, '  p = Product()\n  p.count = self.count\n  p.count = 1\n  return p')
    assert result['complete'] and result['rows'] == [], result


def test_copies_modifier_follows_a_copy_through_an_alias(tmp_path):
    # ``q`` names the same object as ``p``: the write still lands on the returned
    # instance, and the flow analysis, not the spelling, decides that.
    result = run(tmp_path, '  p = Product()\n  q = p\n  q.count = self.count\n  return p')
    assert result['complete'] and len(result['rows']) == 1, result


def test_copies_modifier_rejects_a_copy_of_another_object(tmp_path):
    # ``q`` is a second instance: copying its field is not copying the receiver's.
    result = run(tmp_path, '  p = Product()\n  q = Product()\n  p.count = q.count\n  return p')
    assert result['complete'] and result['rows'] == [], result


def test_return_without_the_modifier_claims_only_a_fresh_allocation(tmp_path):
    # Without the modifier the clause says nothing about fields, which is what
    # makes the modifier load-bearing rather than decorative.
    claim = 'let $replica = construct $unit {}; return $replica;'
    assert len(run(tmp_path, COPY, claim)['rows']) == 1
    assert len(run(tmp_path, '  p = Product()\n  p.count = 1\n  return p', claim)['rows']) == 1


def test_copies_modifier_requires_a_field_role(tmp_path):
    # ``$missing`` is never declared: the copied field must be named by a field
    # role of the pattern, so the claim cannot be satisfied and nothing matches.
    result = run(tmp_path, COPY, 'let $replica = construct $unit {}; return $replica copies $missing;')
    assert result['complete'] and result['rows'] == [], result
