import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.kql2.expressions import EvaluationError
from ken.kql2.values import Option
from ken.structural.model import IR, Entity
from ken.structural_store import Store


def run(body, *, complete=True, entities=True, reference=False):
    program = compile(parse('language "kql/2"; module t; query q {' + body + '}'))
    with Store() as store:
        ir = IR('a.py', 'python')
        if entities:
            for name in ('A', 'B'):
                ir.entities[name] = Entity(name, 'CLASS', name, ir.path, 1, 2)
        unit = store.put_unit('u', ir, 'h', 'v')
        snapshot = store.publish([unit], expected_parent=None, complete=complete)
        return execute(program, store, snapshot, reference=reference)


@pytest.mark.parametrize('reference', [False, True])
def test_ordered_calculations(reference):
    result = run('bind $a = 2 + 3 * 4; bind $b = $a / 2; where $b > 6; select $a, $b;', reference=reference)
    assert result.rows == [(14, 7.0)]


def test_error_barrier_prevents_filter_pushdown():
    with pytest.raises(EvaluationError, match='division by zero'):
        run('bind $a = 1 / 0; where false; select $a;')
    assert run('where false; bind $a = 1 / 0; select $a;').rows == []


def test_error_barrier_prevents_empty_later_join_from_hiding_error():
    with pytest.raises(EvaluationError, match='division by zero'):
        run('bind $a = 1 / 0; class $c { name: "missing"; } select $a;')
    assert run('class $c { name: "missing"; } bind $a = 1 / 0; select $a;').rows == []


@pytest.mark.parametrize('body', [
    'bind $a = $b + 1; bind $b = 2; select $a;',
    'bind $a = true + 1; select $a;',
    'bind $n = count(TypeDecl $c | true | $c); select $c;',
    'from TypeDecl $c; select count(TypeDecl $c | true | $c);',
])
def test_calculation_scope_and_types(body):
    with pytest.raises(CompileError):
        run(body)


@pytest.mark.parametrize('expression,expected', [
    ('count(TypeDecl $c | true | $c)', 2),
    ('count(TypeDecl $c | true | 1)', 1),
    ('sum(TypeDecl $c | true | 3)', 3),
    ('sum_by(TypeDecl $c | true | 3)', 6),
    ('avg(TypeDecl $c | true | 3)', Option(True, 3.0)),
    ('min(TypeDecl $c | true | 3)', Option(True, 3)),
    ('exists(TypeDecl $c | $c.name == "A")', True),
    ('forall(TypeDecl $c | true | $c.name == "A")', False),
])
def test_finite_domains(expression, expected):
    assert run(f'select {expression};').rows == [(expected,)]


@pytest.mark.parametrize('expression,expected', [
    ('count(TypeDecl $c | true | $c)', 0),
    ('sum(TypeDecl $c | true | 3)', 0),
    ('min(TypeDecl $c | true | 3)', Option(False)),
    ('exists(TypeDecl $c | true)', False),
    ('forall(TypeDecl $c | true | false)', True),
])
def test_empty_closed_domains(expression, expected):
    assert run(f'select {expression};', entities=False).rows == [(expected,)]


@pytest.mark.parametrize('expression', [
    'count(TypeDecl $c | true | $c)',
    'exists(TypeDecl $c | $c.name == "missing")',
    'forall(TypeDecl $c | true | true)',
])
def test_open_domains_cannot_certify_absence(expression):
    result = run(f'select {expression};', complete=False)
    assert result.rows == [] and result.unknown_candidates == 1


def test_open_domain_can_prove_witness_or_counterexample():
    assert run('select exists(TypeDecl $c | $c.name == "A");', complete=False).rows == [(True,)]
    assert run('select forall(TypeDecl $c | true | false);', complete=False).rows == [(False,)]
