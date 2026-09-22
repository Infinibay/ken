"""Member places in BODY: ``$place.name`` as a written place and as a read value.

A context object is held in a field of another class, and the state swap writes one of
the *context's* members from another::

    self.holder.slot = self.holder.other

Neither place is a local of the writing method, so the pattern names them through the
retained place (``$back.slot``). The member must belong to that place and be declared
by a field the pattern bound with that name; a read of an unrelated member is not the
described place.
"""
from __future__ import annotations

from ken.kql2.service import search

SOURCE = '''class Holder:
    def __init__(self):
        self.slot = None
        self.other = None

class Writer:
    def __init__(self, holder: Holder):
        self.holder = holder

    def swap(self):
        self.holder.slot = self.holder.other
'''


def query(body: str, fields: str = 'field $slot { } field $other { }') -> str:
    return ('language "kql/2"; module t; query q { '
            f'type $holder {{ {fields} }} '
            'type $writer { field $back { } '
            f'method $swap {{ body {{ {body} }} }} }} select $writer; }}')


def test_member_place_is_written_and_read_through_a_bound_place(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    result = search(tmp_path, query('$back.slot = $back.other as $write;'), cache_mb=0)
    assert result['complete'], result
    assert len(result['rows']) == 1, result


def test_member_name_must_be_a_field_the_pattern_bound(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    # ``slot`` is bound; ``unrelated`` is not a field of the context at all.
    result = search(tmp_path, query('$back.unrelated = $back.other as $write;'), cache_mb=0)
    assert result['complete'] and result['rows'] == []


def test_member_read_must_be_the_described_member(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    # The written value is the member ``other``; asking for a different read is not it.
    result = search(tmp_path, query('$back.slot = $back.slot as $write;'), cache_mb=0)
    assert result['complete'] and result['rows'] == []
