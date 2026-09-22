"""``construct $type { argument ... }`` — the value a construction is built with.

``state#context-transition`` states that the context constructs its first concrete
state *with the context instance itself* (``self.state = Idle(self)``).  The legacy
catalogue read ``CALL_BINDING``/``BINDING_VALUE``/``BINDING_PARAMETER`` for that
occurrence; this is the KQL 2 spelling of the same claim, shared with the ``call``
clause so a construction and a call state their arguments the same way.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

FIXTURE = '''class Holder:
 def __init__(self, owner):
  self.owner = owner
class Context:
 def __init__(self, other):
  self.holder = Holder({arguments})
'''


def query(constraint: str) -> str:
    return ('language "kql/2"; module t; '
            'pattern detect(out TypeDecl $unit, out Call $creation) { '
            'type $holder { constructor $initialize { param $input { } } } '
            'type $unit { method $setup { constructor: true; receiver $self { } body { '
            f'let $made = construct $holder {{ {constraint} }} as $creation; '
            '} } } } '
            'query results { use detect(unit: $unit, creation: $creation); select $unit; }')


def write(tmp_path, arguments: str = 'self') -> None:
    (tmp_path / 'a.py').write_text(FIXTURE.format(arguments=arguments))


def rows(tmp_path, constraint: str) -> list:
    result = search(tmp_path, query(constraint), cache_mb=0)
    assert result['complete'], result
    return result['rows']


def test_construction_argument_matches_by_parameter(tmp_path):
    write(tmp_path)
    assert len(rows(tmp_path, 'argument $self for $input;')) == 1


def test_construction_argument_rejects_another_value(tmp_path):
    # The construction is handed ``other``: the instance never reaches the
    # constructor, so no parameter the pattern can name receives it.
    (tmp_path / 'a.py').write_text(
        'class Holder:\n'
        ' def __init__(self, owner):\n'
        '  self.owner = owner\n'
        'class Context:\n'
        ' def __init__(self, other):\n'
        '  self.holder = Holder(other)\n')
    assert rows(tmp_path, 'argument $self for $input;') == []


def test_construction_argument_position_is_correlated(tmp_path):
    (tmp_path / 'a.py').write_text(
        'class Holder:\n'
        ' def __init__(self, first, second):\n'
        '  self.owner = first\n'
        'class Context:\n'
        ' def __init__(self, other):\n'
        '  self.holder = Holder(other, self)\n')
    assert rows(tmp_path, 'argument $self at 0;') == []
    assert len(rows(tmp_path, 'argument $self at 1;')) == 1


def test_construction_argument_at_any_accepts_any_position(tmp_path):
    write(tmp_path)
    assert len(rows(tmp_path, 'argument $self at any;')) == 1


def test_construction_argument_requires_a_bound_operand(tmp_path):
    write(tmp_path)
    # ``$missing`` is never declared: an argument origin names a place the pattern
    # bound, otherwise the spelling is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query('argument $missing at 0;'), cache_mb=0)
