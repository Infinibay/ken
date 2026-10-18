"""Conditional local aliases choose a value on the same source route."""
import pytest

from ken.kql2.service import search


@pytest.mark.parametrize('expression,expected', [
    ('made if flag else None', [['f']]),
    ('None if flag else made', [['f']]),
    ('made if True else None', [['f']]),
    ('made if False else None', []),
    ('None if True else made', []),
    ('None if flag else None', []),
    ('None if (True) else made', []),
    ('made if (False) else None', []),
])
@pytest.mark.parametrize('assignment', [True, False])
def test_conditional_alias_expression(tmp_path, expression, expected, assignment):
    suffix = f' alias = {expression}\n return alias\n' if assignment else f' return {expression}\n'
    (tmp_path/'sample.py').write_text(
        'def mark_safe(value): return value\n'
        'def f(value, flag):\n made = mark_safe(value)\n' + suffix
    )
    result = search(tmp_path, '''language "kql/2"; module regression.expression_alias;
      query q {callable $f {name:"f"; body {
        let $v = call $s {name:"mark_safe";}; return $v;
      }} select $f.name;}''', cache_mb=0)
    assert result['rows'] == expected
    assert result['unknown_candidates'] == 0


@pytest.mark.parametrize('operand', ['made', 'made if True else None', 'None if False else made'])
def test_ordinary_yield_of_a_known_local_does_not_inject_throw(tmp_path, operand):
    (tmp_path/'sample.py').write_text('''def mark_safe(value): return value
def f(value):
 made = mark_safe(value)
 try:
  yield OPERAND
 except ValueError:
  return made
'''.replace('OPERAND', operand))
    result = search(tmp_path, '''language "kql/2"; module regression.yield_exception;
      query q {callable $f {name:"f"; body {
        let $v = call $s {name:"mark_safe";}; return $v;
      }} select $f.name;}''', cache_mb=0)
    assert result['rows'] == []
