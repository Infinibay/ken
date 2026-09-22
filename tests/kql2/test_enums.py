import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.kql2.values import EnumValue
from ken.structural_store import Store


def run(text):
    program = compile(parse('language "kql/2"; module t; ' + text))
    with Store() as store:
        snapshot = store.publish([], expected_parent=None, complete=False)
        return execute(program, store, snapshot)


def test_enum_domain_is_closed_independently_of_source_coverage():
    result = run('enum State { fresh, used, closed } query q { from State $s; where $s != State.closed; select $s; }')
    assert set(result.rows) == {(EnumValue('State','fresh'),), (EnumValue('State','used'),)}
    assert result.unknown_candidates == 0


def test_enum_aggregate_and_recursion():
    result = run('''enum State { fresh, used, closed }
      predicate Step(State $a, State $b) {
        ($a == State.fresh and $b == State.used) or ($a == State.used and $b == State.closed)
      }
      predicate Reach(State $a, State $b) {
        Step($a,$b) or exists(State $m | Step($a,$m) and Reach($m,$b))
      }
      query q { select count(State $s | Reach(State.fresh,$s) | $s); }
    ''')
    assert result.rows == [(2,)]


@pytest.mark.parametrize('text', [
    'enum S { a, a } query q { select 1; }',
    'enum TypeDecl { a } query q { select 1; }',
    'enum S { a } query q { select S.b; }',
    'enum S { a } enum T { a } query q { where S.a == T.a; select 1; }',
    'enum S { a } query q { from S $s; class $s {} select $s; }',
    'enum S { a } predicate P(TypeDecl $s) { true } query q { where P(S.a); select 1; }',
])
def test_enum_type_errors(text):
    with pytest.raises(CompileError):
        run(text)


def test_enum_domain_in_named_pattern():
    result = run('''enum State { fresh, used }
      pattern Fresh(out State $s) { from State $s; where $s == State.fresh; }
      pattern Check(in State $s) { where $s == State.fresh; }
      query q { use Fresh(s:$s); use Check(s:$s); select $s; }
    ''')
    assert result.rows == [(EnumValue('State','fresh'),)]
