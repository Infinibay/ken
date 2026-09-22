"""``return_type: applied($unit, $state)`` states a generic return instantiation.

The IR publishes ``RETURN_TYPE_ARGUMENT(callable, argument)`` only when a
callable's declared return type applies its *own* declaring type, and the bare
type name cannot say which argument it was applied to (IR 1.65). The matcher
names both the base and the argument so a pattern can say "a step of this
builder returns another instantiation of it, in state ``$state``".
"""
import json
import pathlib
import tempfile

import pytest

from ken.kql2.service import search

GENERIC_BUILDER = '''struct Pending;
struct Ready;

struct Builder<State> { accumulated: i32, state: State }

impl Builder<Pending> {
    fn with_value(self, input: i32) -> Builder<Pending> { Builder { accumulated: input, state: Pending } }
    fn ready(self) -> Builder<Ready> { Builder { accumulated: self.accumulated, state: Ready } }
    fn size(self) -> i32 { self.accumulated }
}
'''

PARAMETER_BUILDER = '''struct Builder<State> { state: State }

impl Builder<State> {
    fn reset(self) -> Builder<State> { Builder { state: self.state } }
}
'''

CLAUSE = ('type $unit { type_parameter $state_parameter; '
          'method $step { return_type: applied($unit, $state); } }')


def match(clause, source=GENERIC_BUILDER, extension='rs', selection='$unit'):
    directory = pathlib.Path(tempfile.mkdtemp())
    (directory / ('builder.' + extension)).write_text(source)
    query = ('language "kql/2"; module t; query q { ' + clause + ' select ' + selection + '; }')
    return search(directory, query, cache_mb=0)['rows']


def test_applied_binds_the_type_argument_of_each_return_instantiation():
    rows = match(CLAUSE, selection='$unit, $state')
    assert len(rows) == 2, rows
    assert {row[1] for row in rows} == {'Pending', 'Ready'}, rows


def test_a_primitive_return_type_is_not_an_instantiation():
    # ``size(self) -> i32`` applies no type argument, so only the two generic
    # steps can bind the clause.
    assert 'i32' not in json.dumps(match(CLAUSE))


def test_the_declared_parameter_name_is_the_other_end_of_the_comparison():
    assert not match(CLAUSE + ' where $state != $state_parameter;',
                     source=PARAMETER_BUILDER)
    same = CLAUSE + ' where $state == $state_parameter;'
    assert len(match(same, source=PARAMETER_BUILDER)) == 1


def test_applied_requires_the_enclosing_type_as_its_base():
    clause = ('type $unit { type_parameter $state_parameter; '
              'method $step { return_type: applied($other, $state); } } '
              'type $other { }')
    with pytest.raises(Exception) as failure:
        match(clause)
    assert 'applied requires the enclosing type as its base' in str(failure.value)
