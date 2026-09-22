import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.kql2.service import search
from ken.structural.model import IR, Entity
from ken.structural_store import Store


HEADER = 'language "kql/2"; module test; '


def run(text, **budgets):
    program = compile(parse(HEADER + text))
    with Store() as store:
        ir = IR('a.py', 'python')
        for name in ('A', 'B', 'C', 'D'):
            ir.entities[name] = Entity(name, 'CLASS', name, ir.path, 1, 2)
        uid = store.put_unit('u', ir, 'h', 'v')
        return execute(program, store, store.publish([uid], expected_parent=None), **budgets)


EDGES = '''predicate Edge(TypeDecl $a, TypeDecl $b) {
    ($a.name == "A" and $b.name == "B")
    or ($a.name == "B" and $b.name == "C")
    or ($a.name == "C" and $b.name == "A")
}'''
REACH = '''predicate Reach(TypeDecl $a, TypeDecl $b) {
    Edge($a, $b) or exists(TypeDecl $m | Edge($a, $m) and Reach($m, $b))
}'''


def test_recursive_transitive_closure_matches_independent_oracle():
    result = run(EDGES + REACH + 'query q { from TypeDecl $a, TypeDecl $b; where Reach($a,$b); select $a.name,$b.name; }')
    edges = {('A', 'B'), ('B', 'C'), ('C', 'A')}
    closure = set(edges)
    while True:
        extended = closure | {(a, d) for a, b in closure for c, d in edges if b == c}
        if extended == closure:
            break
        closure = extended
    assert result.complete and set(result.rows) == closure


def test_mutual_recursion_and_stratified_negation():
    result = run('''
      predicate A(TypeDecl $x) { $x.name == "A" or B($x) }
      predicate B(TypeDecl $x) { A($x) }
      predicate Other(TypeDecl $x) { not B($x) }
      query q { from TypeDecl $x; where Other($x); select $x.name; }
    ''')
    assert set(result.rows) == {('B',), ('C',), ('D',)}


@pytest.mark.parametrize('body', [
    'predicate P(TypeDecl $a) { not P($a) }',
    'predicate P(TypeDecl $a) { P($a) == false }',
    'predicate P(TypeDecl $a) { count(TypeDecl $b | P($b) | $b) > 0 }',
    'predicate P(TypeDecl $a) { forall(TypeDecl $b | true | P($b)) }',
    'predicate P(TypeDecl $a) { 3 }',
    'predicate P(Int $a) { true }',
    'predicate P(TypeDecl $a, TypeDecl $a) { true }',
    'predicate P(TypeDecl $a) { Missing($a) }',
])
def test_invalid_predicates_fail_at_compilation(body):
    with pytest.raises(CompileError):
        run(body + 'query q { select 1; }')


def test_predicate_argument_type_is_not_just_entity():
    with pytest.raises(CompileError, match='declared domain'):
        run('predicate P(Callable $c) { true } query q { class $c {} where P($c); select $c; }')


def test_recursive_query_budget_reports_incomplete():
    result = run(EDGES + REACH + 'query q { from TypeDecl $a, TypeDecl $b; where Reach($a,$b); select $a,$b; }', max_states=40)
    assert not result.complete and result.reason == 'max_states'


def test_unknown_property_not_proven_false():
    result = run('predicate P(TypeDecl $a) { $a.native_kind == "class" } query q { from TypeDecl $a; where not P($a); select $a; }')
    assert result.rows == [] and result.unknown_candidates == 4


def test_predicate_compilation_roundtrips_disk(tmp_path):
    from ken.kql2.compilation import clear_compilation_cache
    (tmp_path / 'a.py').write_text('class A: pass')
    text = HEADER + 'predicate P(TypeDecl $a) { $a.name == "A" } query q { class $a {} where P($a); select $a.name; }'
    assert search(tmp_path, text)['rows'] == [['A']]
    clear_compilation_cache()
    result = search(tmp_path, text)
    assert result['rows'] == [['A']]
    assert result['analysis']['compilation_cache']['status'] == 'disk_hit'


def test_more_than_32_recursive_hops():
    edges = ' or '.join(f'($a.name == "N{i:02}" and $b.name == "N{i+1:02}")' for i in range(36))
    text = HEADER + 'predicate Edge(TypeDecl $a, TypeDecl $b) {' + edges + '}' + REACH + '''
      query q { class $a { name: "N00"; } class $b { name: "N36"; }
                where Reach($a,$b); select $a.name,$b.name; }
    '''
    p = compile(parse(text))
    with Store() as store:
        ir = IR('a','python')
        for i in range(37):
            name = f'N{i:02}'
            ir.entities[name] = Entity(name,'CLASS',name,'a',1,1)
        uid = store.put_unit('u',ir,'h','v')
        result = execute(p,store,store.publish([uid],expected_parent=None),timeout_ms=None,max_states=2_000_000)
        assert result.complete and result.rows == [('N00','N36')]


def test_dependency_components_handle_long_acyclic_chain_without_call_stack():
    from dataclasses import replace
    from ken.kql2.logic import Predicate, components
    declaration=parse(HEADER+'predicate P(TypeDecl $a) { P($a) }').declarations[0]
    predicates=tuple(Predicate(f'P{i}',declaration.parameters,
        replace(declaration.formula,value=f'P{i+1}')) for i in range(2500))
    last=parse(HEADER+'predicate End(TypeDecl $a) { true }').declarations[0]
    predicates += (Predicate('P2500',last.parameters,last.formula),)
    groups=components(predicates)
    assert len(groups) == 2501 and all(len(group) == 1 for group in groups)
