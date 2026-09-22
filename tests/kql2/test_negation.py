import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.structural.frontend import lower_source
from ken.structural_store import Store


def run(query, source='class A:\n def work(self): pass\nclass B: pass\n', complete=True):
    p = compile(parse('language "kql/2"; module t; ' + query))
    with Store() as store:
        unit = store.put_unit('u', lower_source(source, 'python', 'a.py'), 'h', 'v')
        return execute(p, store, store.publish([unit], expected_parent=None, complete=complete))


def test_correlated_anti_join_does_not_use_another_class_method():
    result = run('query q { class $c { not exists { method $m { name: "work"; } } } select $c.name; }')
    assert result.rows == [('B',)]


def test_open_world_cannot_prove_absence():
    result = run('query q { class $c { not exists { method $m {} } } select $c.name; }', complete=False)
    assert result.rows == [] and result.unknown_candidates == 1


def test_negative_roles_cannot_escape():
    with pytest.raises(CompileError, match='unbound'):
        run('query q { not exists { class $c {} } select $c; }')


def test_global_negation_empty_and_nonempty():
    query = 'query q { not exists { class $c {} } select 1; }'
    assert run(query).rows == []
    assert run(query, source='x=1').rows == [(1,)]


def test_predicate_in_anti_join():
    result = run('''predicate Work(Callable $m) { $m.name == "work" }
      query q { class $c { not exists { method $m {} where Work($m); } } select $c.name; }''')
    assert result.rows == [('B',)]


def test_named_pattern_quantifier_hygiene():
    result = run('''pattern Empty(out TypeDecl $c) {
      class $c {} where not exists(Callable $m | owns($c,$m));
    }
    query q { use Empty(c:$a); use Empty(c:$b); select $a.name,$b.name; }''')
    assert result.rows == [('B','B')]


def test_parameter_position_and_regex_inside_anti_join():
    result = run('''query q {
      class $c { not exists { method $m { param $p { position: 0; name: /task/; } } } }
      select $c.name;
    }''', source='class A:\n def work(self,task): pass\nclass B:\n def work(self,other): pass\n')
    assert result.rows == [('B',)]
