"""``if (binary(left: $p, operator: _, right: _))`` — a condition without its operator.

``state.event_transition`` requires the state's action to *test the request event*
(legacy ``PARAMETER_TEST``), and the fixtures test it with ``event > 0`` and
``if(event>0)``.  Naming the operator would make the pattern language-specific, so
the condition accepts the source-expression form the argument derivations use:
``operator:`` takes ``_``, a string, or a list of strings.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

FIXTURE = '''def sink(value):
    return value
class Machine:
 def watch(self, state, event):
  if {condition}:
   sink(event)
'''


def query(condition: str, match: str) -> str:
    return ('language "kql/2"; module t; pattern detect(out Callable $action) { '
            'type $unit { method $action { name: "watch"; '
            'param $state { name: "state"; } param $event { name: "event"; } body { '
            f'if ({condition}) {{ call $sink {{ name: "sink"; {match} }}; }} '
            '} } } } '
            'query results { use detect(action: $action); select $action; }')


def write(tmp_path, condition: str) -> None:
    (tmp_path / 'a.py').write_text(FIXTURE.format(condition=condition))


def rows(tmp_path, condition: str, match: str = 'argument $event at 0;') -> list:
    result = search(tmp_path, query(condition, match), cache_mb=0)
    assert result['complete'], result
    return result['rows']


ANY_OPERATOR = 'binary(left: $event, operator: _, right: _)'


def test_wildcard_operator_matches_a_greater_than_test(tmp_path):
    write(tmp_path, 'event > 0')
    assert len(rows(tmp_path, ANY_OPERATOR)) == 1


def test_wildcard_operator_rejects_a_test_of_another_place(tmp_path):
    # The condition compares ``state``, not the event: the pattern names the place.
    write(tmp_path, 'state is not None')
    assert rows(tmp_path, ANY_OPERATOR) == []


def test_named_operator_pins_the_spelling(tmp_path):
    write(tmp_path, 'event > 0')
    assert len(rows(tmp_path, 'binary(left: $event, operator: ">", right: _)')) == 1
    assert rows(tmp_path, 'binary(left: $event, operator: "==", right: _)') == []


def test_operator_list_accepts_either_spelling(tmp_path):
    write(tmp_path, 'event != 0')
    chosen = 'binary(left: $event, operator: [">", "!="], right: _)'
    assert len(rows(tmp_path, chosen)) == 1


def test_condition_still_requires_a_bound_place(tmp_path):
    write(tmp_path, 'event > 0')
    with pytest.raises(Exception):
        rows(tmp_path, 'binary(left: $missing, operator: _, right: _)')
