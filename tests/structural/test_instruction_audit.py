"""Regressions found by the independent review of the instruction adapter."""
import pytest

from .test_instruction_ir import program


@pytest.mark.parametrize('operator', ['+=','-=','*=','/=','//=','%=','**=','<<=','>>=','&=','|=','^='])
def test_augmented_assignment_never_becomes_plain_replacement(operator):
    p=program(f'def f(x):\n x {operator} 3\n return x\n')
    f=p.functions[0]
    assert f.status=='partial'
    assert not any(i.opcode=='slot.store' for i in f.body.instructions)
    assert any(i.opcode=='native' and i.attrs['reason']=='assignment-lowering' for i in f.body.instructions)


def test_java_shift_assignment_is_not_a_constant_store():
    p=program('class C{int f(int x){x<<=2;return x;}}','java')
    assert not any(i.opcode=='slot.store' for i in p.functions[0].body.instructions)
    assert p.functions[0].status=='partial'


@pytest.mark.parametrize('loop',['while','for'])
def test_exhaustion_clause_is_not_dropped(loop):
    statement='while x' if loop=='while' else 'for x in xs'
    p=program(f'def f(x,xs):\n {statement}:\n  x=0\n else:\n  x=3\n return x\n')
    f=p.functions[0]
    assert f.status=='partial'
    assert f.body.instructions[0].opcode=='native'
    assert f.body.instructions[0].attrs['reason']=='loop-exhaustion-clause'


@pytest.mark.parametrize('language,source', [
    ('cpp','class X{int field;public:X(int y):field(y){}};'),
    ('csharp','class X{X(int x){} X():this(expensive()){} static int expensive(){return 1;}}'),
])
def test_initialization_outside_constructor_body_is_not_omitted(language, source):
    p=program(source,language)
    initializers=[(f,i) for f in p.functions for i in f.body.instructions if i.attrs.get('reason')=='constructor-initialization']
    assert len(initializers)==1,p.format()
    assert initializers[0][0].status=='partial'
    assert initializers[0][1].opcode=='native' and 'unknown' in initializers[0][1].effects


@pytest.mark.parametrize('language',['javascript','typescript'])
@pytest.mark.parametrize('expression',['obj?.method(expensive())','obj.method?.(expensive())','obj?.child.method(expensive())','obj?.[expensive()]'])
def test_optional_evaluation_does_not_unconditionally_run_arguments(language,expression):
    p=program(f'function f(obj){{return {expression};}}',language)
    f=p.functions[0]
    assert f.status=='partial'
    assert not any(i.opcode=='call' for i in f.body.instructions)
    assert any(i.attrs.get('reason')=='optional-evaluation' for i in f.body.instructions)


CALLABLES={
    'python':'def f(cb,other,x):\n REBIND\n return cb(x)\n',
    'javascript':'function f(cb,other,x){REBIND return cb(x);}',
    'typescript':'function f(cb:(x:number)=>number,other:(x:number)=>number,x:number){REBIND return cb(x);}',
    'csharp':'class C{int f(System.Func<int,int> cb,System.Func<int,int> other,int x){REBIND return cb(x);}}',
    'go':'package p\nfunc f(cb func(int)int,other func(int)int,x int)int {REBIND return cb(x)}',
    'rust':'fn f(mut cb:fn(i32)->i32,other:fn(i32)->i32,x:i32)->i32 {REBIND return cb(x);}',
}


@pytest.mark.parametrize('language',CALLABLES)
@pytest.mark.parametrize('rebound',[False,True])
def test_callable_parameter_is_loaded_as_a_value_at_its_call(language,rebound):
    replacement=('cb=other' if language=='python' else 'cb=other;') if rebound else ('pass' if language=='python' else '')
    p=program(CALLABLES[language].replace('REBIND',replacement),language)
    f=p.functions[0]
    call=next(i for i in f.body.instructions if i.opcode=='call')
    callee=next(o for o in call.operands if o.role=='callee')
    assert callee.kind=='value',p.format()
    definition=next(i for i in f.body.instructions if i.result==callee.ref)
    assert definition.opcode=='slot.load'
    slot=definition.operands[0].ref
    assert f.places[slot]['name']=='cb'
    stores=[i for i in f.body.instructions if i.opcode=='slot.store' and i.operands[0].ref==slot]
    assert len(stores)==int(rebound)
    if rebound: assert f.body.instructions.index(stores[0]) < f.body.instructions.index(definition)


@pytest.mark.parametrize('language',['python','javascript'])
def test_member_name_matching_a_parameter_is_not_a_local_callee(language):
    source='def f(obj,run,x):\n return obj.run(x)\n' if language=='python' else 'function f(obj,run,x){return obj.run(x);}'
    p=program(source,language)
    call=next(i for i in p.functions[0].body.instructions if i.opcode=='call')
    callee=next(o for o in call.operands if o.role=='callee')
    assert callee.kind=='symbol' and callee.ref=='run'
    assert any(o.role=='receiver' for o in call.operands)
