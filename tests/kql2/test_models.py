import pytest

from ken.kql2 import parse
from ken.kql2.compiler import compile, CompileError
from ken.kql2.execution import execute
from ken.structural.model import IR, Entity
from ken.structural_store import Store


TEXT = '''language "kql/2"; module t;
signature Choice { predicate accept(TypeDecl $x); }
model First implements Choice { predicate accept(TypeDecl $x) { $x.name == "A" } }
model Second implements Choice { predicate accept(TypeDecl $x) { $x.name == "B" } }
pattern Choose<M: Choice>(out TypeDecl $x) { class $x {} where M.accept($x); }
'''


def test_independent_model_instantiations():
    program = compile(parse(TEXT + 'query q { use Choose<First>(x:$a); use Choose<Second>(x:$b); select $a.name,$b.name; }'))
    with Store() as store:
        ir = IR('a','python')
        for name in ('A','B'):
            ir.entities[name] = Entity(name,'CLASS',name,'a',1,1)
        unit = store.put_unit('u',ir,'h','v')
        result = execute(program,store,store.publish([unit],expected_parent=None))
        assert result.rows == [('A','B')]


@pytest.mark.parametrize('change', [
    lambda text:text.replace('implements Choice', 'implements Missing'),
    lambda text:text.replace('accept(TypeDecl $x) { $x.name == "A" }', 'accept(Callable $x) { $x.name == "A" }'),
    lambda text:text.replace('Choose<First>', 'Choose<Missing>'),
    lambda text:text.replace('Choose<First>', 'Choose<First,Second>'),
    lambda text:text.replace('Choose<First>', 'Choose'),
])
def test_invalid_model_contracts(change):
    with pytest.raises(CompileError):
        compile(parse(change(TEXT + 'query q { use Choose<First>(x:$a); select $a; }')))


def test_model_internal_predicates_are_qualified():
    text = TEXT.replace('predicate accept(TypeDecl $x) { $x.name == "A" }',
                        'predicate accept(TypeDecl $x) { inner($x) } predicate inner(TypeDecl $x) { $x.name == "A" }')
    program = compile(parse(text + 'query q { use Choose<First>(x:$a); select $a; }'))
    assert any(p.name == 'First.inner' for p in program.predicates)


def test_nested_model_forwarding():
    text = TEXT + '''pattern Outer<N: Choice>(out TypeDecl $x) { use Choose<N>(x:$x); }
       query q { use Outer<First>(x:$a); select $a; }'''
    assert compile(parse(text)).scans[0].role == 'a'
