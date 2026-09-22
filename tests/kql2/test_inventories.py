import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.structural.frontend import lower_source
from ken.structural_store import Store


def run(source, query, *, language='python', complete=True, reference=False):
    program = compile(parse('language "kql/2"; module t; query q {' + query + '}'))
    with Store() as store:
        unit = store.put_unit('u', lower_source(source, language, 'a'), 'h', 'v')
        return execute(program, store, store.publish([unit], expected_parent=None, complete=complete), reference=reference)


@pytest.mark.parametrize('language,source', [
    ('python','class A:\n def work(self,task): pass\n'),
    ('java','class A { void work(String task) {} }'),
    ('typescript','class A { work(task: string) {} }'),
    ('cpp','class A { void work(int task) {} };'),
    ('csharp','class A { void work(string task) {} }'),
])
def test_exact_parameters_excludes_receiver(language, source):
    query = 'class $c { method $m { name: "work"; parameters exact { param $p { name: "task"; } } } } select $p.name;'
    assert run(source, query, language=language).rows == [('task',)]
    assert run(source, query, language=language, reference=True).rows == [('task',)]


def test_exact_parameters_rejects_extra_parameter_and_open_inventory():
    query = 'callable $m { parameters exact { param $p { name: "task"; } } } select $m;'
    assert run('def work(task, extra): pass', query).rows == []
    result = run('def work(task): pass', query, complete=False)
    assert result.rows == [] and result.unknown_candidates == 1


def test_empty_exact_fields():
    query = 'class $c { fields exact {} } select $c.name;'
    assert run('class A {} class B { int x; }', query, language='java').rows == [('A',)]


def test_repeated_field_capture_uses_distinct_inventory():
    query = 'class $c { fields exact { field $x {} field $y {} } } select $c.name;'
    assert run('class A { int x; }', query, language='java').rows == [('A',)]


def test_optional_never_filters_required_matches():
    query = 'class $c { optional { method $m { name: "work"; } } } select $c.name;'
    result = run('class A:\n def work(self): pass\nclass B: pass', query)
    assert set(result.rows) == {('A',), ('B',)}
    assert {e['status'] for e in result.optional_evidence} == {'matched', 'absent'}
    result = run('class B: pass', query, complete=False)
    assert result.rows == [('B',)] and result.optional_evidence[0]['status'] == 'unknown'


def test_optional_role_cannot_escape():
    with pytest.raises(CompileError, match='unbound'):
        run('class A: pass', 'optional { class $c {} } select $c;')


def test_exact_owner_checked_even_with_empty_inventory():
    with pytest.raises(CompileError, match='owner type'):
        run('def f(): pass', 'callable $m { fields exact {} } select $m;')
