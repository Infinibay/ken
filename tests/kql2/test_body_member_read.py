"""Assigning from a member read of the bound place is that place's value.

``$state = $stored`` matches ``self.state = other.stored``: the assignment value is a
member occurrence that flows into the place the pattern bound, not the place entity
itself. Requiring the identity alone would only match the rarer ``self.state = stored``.
"""
from ken.kql2.service import search

QUERY = '''language "kql/2"; module t; query q {
 type $snapshot {
   field $stored { }
 }
 type $unit {
   field $state { }
   method $restore {
     name: "restore";
     param $supplied { }
     body {
       $state = $stored as $store;
     }
   }
 }
 select $restore.name;
}'''


def test_a_member_read_of_the_bound_place_is_its_value(tmp_path):
    (tmp_path / 'a.py').write_text('class Snapshot:\n def __init__(self, value): self.stored = value\n'
                                   'class Unit:\n def restore(self, supplied: Snapshot): self.state = supplied.stored\n')
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == [['restore']]


def test_assigning_something_else_is_not_that_place(tmp_path):
    (tmp_path / 'a.py').write_text('class Snapshot:\n def __init__(self, value): self.stored = value\n'
                                   'class Unit:\n def restore(self, supplied: Snapshot): self.state = 0\n')
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == []
