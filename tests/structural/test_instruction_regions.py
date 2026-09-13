"""Conditional evaluation and per-iteration identities required by GoF algorithms."""
import copy
import json

import pytest

from ken.structural.instructions import Program
from .test_instruction_ir import program


def instructions(region):
    for i in region.instructions:
        yield i
        for r in i.regions:
            yield from instructions(r)


def wrapper(language, expression):
    return {
        'python': f'def f(a,b):\n return {expression}\n',
        'javascript': f'function f(a,b){{return {expression};}}',
        'typescript': f'function f(a:boolean,b:boolean){{return {expression};}}',
        'java': f'class C{{boolean f(boolean a,boolean b){{return {expression};}}}}',
        'go': f'package p\nfunc f(a bool,b bool) bool {{return {expression}}}',
        'rust': f'fn f(a:bool,b:bool)->bool {{return {expression};}}',
    }[language]


@pytest.mark.parametrize('language', ['python','javascript','typescript','java','go','rust'])
@pytest.mark.parametrize('operation', ['and','or'])
@pytest.mark.parametrize('nested', [False, True])
def test_short_circuit_keeps_rhs_call_inside_selected_region(language, operation, nested):
    op = operation if language == 'python' else {'and':'&&','or':'||'}[operation]
    expression = f'a {op} probe(b)'
    if nested: expression = f'a {op} (b {op} probe(a))'
    p = program(wrapper(language, expression), language)
    f = p.functions[0]
    assert not any(i.opcode == 'call' for i in f.body.instructions)
    choices = [i for i in instructions(f.body) if i.opcode == 'short_circuit']
    assert len(choices) == (2 if nested else 1), p.format()
    assert all(i.attrs['operator'] == op for i in choices)
    call = next(i for i in instructions(choices[-1].regions[0]) if i.opcode == 'call')
    assert choices[-1].regions[0].outputs == [call.result]
    assert f.body.instructions[-1].operands[0].ref == choices[0].result
    assert Program.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()


@pytest.mark.parametrize('language', ['python','javascript','typescript','java','csharp'])
@pytest.mark.parametrize('nested', [False, True])
def test_choose_evaluates_condition_once_and_keeps_both_calls_local(language, nested):
    expression = 'left() if condition() else right()' if language == 'python' else 'condition() ? left() : right()'
    if nested:
        expression = f'({expression}) if a else fallback()' if language == 'python' else f'a ? ({expression}) : fallback()'
    source = f'class C{{int f(bool a){{return {expression};}}}}' if language == 'csharp' else wrapper(language, expression)
    p = program(source, language)
    f = p.functions[0]
    choices = [i for i in instructions(f.body) if i.opcode == 'choose']
    assert len(choices) == (2 if nested else 1), p.format()
    choice = choices[-1]
    assert [r.kind for r in choice.regions] == ['consequence','alternative']
    for r in choice.regions:
        assert r.outputs == [r.instructions[-1].result]
        assert any(i.opcode == 'call' for i in r.instructions)
    assert f.body.instructions[-1].operands[0].ref == choices[0].result
    assert Program.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()


@pytest.mark.parametrize('length', [1,2,5,12])
@pytest.mark.parametrize('with_else', [False, True])
def test_elif_tests_are_nested_only_in_prior_alternative(length, with_else):
    source = 'def f(x):\n if check0(x):\n  arm0()\n'
    for n in range(1,length + 1): source += f' elif check{n}(x):\n  arm{n}()\n'
    if with_else: source += ' else:\n  otherwise()\n'
    p = program(source)
    region = p.functions[0].body
    for n in range(length + 1):
        call = next(i for i in region.instructions if i.opcode == 'call')
        assert any(o.ref == f'check{n}' for o in call.operands)
        branch = next(i for i in region.instructions if i.opcode == 'if')
        assert branch.operands[0].ref == call.result
        if n < length: region = branch.regions[1]
    assert len(branch.regions) == (2 if with_else else 1)


ITERATIONS = {
    'python': 'def f(xs):\n for item in xs:\n  audit(1)\n  consume(item)\n',
    'javascript': 'function f(xs){for(const item of xs){audit(1);consume(item);}}',
    'typescript': 'function f(xs:Item[]){for(const item of xs){audit(1);consume(item);}}',
    'java': 'class C{void f(Item[] xs){for(Item item:xs){audit(1);consume(item);}}}',
    'csharp': 'class C{void f(Item[] xs){foreach(Item item in xs){audit(1);consume(item);}}}',
    'rust': 'fn f(xs:Vec<Item>){for item in xs {audit(1);consume(item);}}',
}


@pytest.mark.parametrize('language', ITERATIONS)
@pytest.mark.parametrize('rebound', [False,True])
def test_iteration_has_per_turn_value_and_rebinding_is_visible(language, rebound):
    source = ITERATIONS[language]
    if rebound:
        source = source.replace('consume(item)', 'item=other\n  consume(item)' if language == 'python' else 'item=other;consume(item)')
    p = program(source, language)
    f = p.functions[0]
    loop = next(i for i in f.body.instructions if i.opcode == 'iterate')
    assert loop.attrs['evaluation'] == 'iterable-once'
    assert loop.effects == ['invoke','unknown']
    body = loop.regions[0]
    assert body.instructions[0].opcode == 'iteration.value'
    stores = [i for i in body.instructions if i.opcode == 'slot.store']
    assert len(stores) == (2 if rebound else 1)
    assert stores[0].operands[1].ref == body.instructions[0].result
    assert f.places[stores[0].operands[0].ref]['name'] == 'item'
    assert not any(i.opcode == 'call' for i in f.body.instructions)
    assert Program.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()


@pytest.mark.parametrize('language,source', [
    ('javascript','function f(xs){for(const key in xs){use(key);}}'),
    ('javascript','async function f(xs){for await(const x of xs){use(x);}}'),
    ('python','async def f(xs):\n async for x in xs:\n  use(x)\n'),
    ('python','def f(xs):\n for x in xs: use(x)\n else: done()\n'),
    ('python','def f(xs):\n for x,y in xs: use(x)\n'),
    ('go','package p\nfunc f(xs []int){for i,x:=range xs {use(i,x)}}'),
    ('cpp','void f(){for(auto x:xs){use(x);}}'),
    ('csharp','class C{bool F(A a,A b){return a && b;}}'),
    ('cpp','bool f(A a,A b){return a && b;}'),
])
def test_unresolved_protocols_remain_native(language, source):
    p = program(source, language)
    f = p.functions[0]
    assert f.status == 'partial'
    assert any(i.opcode == 'native' for i in instructions(f.body)), p.format()


@pytest.mark.parametrize('corruption', ['missing-arm','missing-output','escaped-value','rhs-count','wrong-operator','element-outside','element-duplicate'])
def test_verifier_rejects_invalid_control_contracts(corruption):
    p = program('def f(xs,a):\n for x in xs: consume(x)\n return left() if a else right()\n')
    f = p.functions[0]
    choice = next(i for i in f.body.instructions if i.opcode == 'choose')
    loop = next(i for i in f.body.instructions if i.opcode == 'iterate')
    if corruption == 'missing-arm': choice.regions.pop()
    elif corruption == 'missing-output': choice.regions[0].outputs.clear()
    elif corruption == 'escaped-value': f.body.instructions[-1].operands[0].ref = choice.regions[0].outputs[0]
    elif corruption == 'rhs-count': choice.opcode = 'short_circuit'; choice.attrs['operator'] = 'and'
    elif corruption == 'wrong-operator':
        choice.opcode = 'short_circuit'; choice.regions = choice.regions[:1]; choice.regions[0].kind = 'rhs'; choice.attrs['operator'] = '+'
    elif corruption == 'element-outside': f.body.instructions.insert(0,loop.regions[0].instructions.pop(0))
    else: loop.regions[0].instructions.insert(1,copy.deepcopy(loop.regions[0].instructions[0]))
    with pytest.raises(ValueError): p.verify()


@pytest.mark.parametrize('language,source', [
    ('java','class C{Item field; C(Item input){this.field=input;}}'),
    ('csharp','class C{Item field; C(Item input){this.field=input;}}'),
    ('typescript','class C{field:Item; constructor(input:Item){this.field=input;}}'),
    ('javascript','class C{constructor(input){this.field=input;}}'),
    ('python','class C:\n def __init__(self,input): self.field=input\n'),
])
def test_constructor_body_exposes_retained_input_instead_of_implicit_return(language, source):
    p = program(source, language)
    f = p.functions[0]
    stores = [i for i in f.body.instructions if i.opcode == 'memory.store']
    assert len(stores) == 1, p.format()
    assert not any(i.opcode == 'return' for i in f.body.instructions)
    assert not any(i.opcode == 'native' for i in f.body.instructions), p.format()


def loop_source(language, body):
    if language in {'javascript','typescript'}: return f'function f(){{{body}}}'
    if language == 'cpp': return f'void f(){{{body}}}'
    return f'class C{{void f(){{{body}}}}}'


@pytest.mark.parametrize('language', ['javascript','typescript','java','csharp','cpp'])
@pytest.mark.parametrize('form', ['for','do'])
@pytest.mark.parametrize('exit_', ['break','continue','none'])
def test_counted_and_post_test_loops_preserve_regions(language, form, exit_):
    prefix = 'let' if language in {'javascript','typescript'} else 'int'
    action = f'if(stop()){{{exit_};}}' if exit_ != 'none' else ''
    body = f'for({prefix} i=start();test(i);i=advance(i)){{audit(1);{action}use(i);}}' if form == 'for' else f'do{{audit(1);{action}use(1);}}while(test());'
    p = program(loop_source(language,body),language)
    f = p.functions[0]
    assert [i.opcode for i in f.body.instructions] == ['loop'], p.format()
    loop = f.body.instructions[0]
    assert loop.attrs['form'] == form
    assert [r.kind for r in loop.regions] == (['init','test','body','update'] if form == 'for' else ['body','test'])
    assert loop.attrs['continue_region'] == ('update' if form == 'for' else 'test')
    for r in loop.regions:
        if r.kind == 'test': assert r.outputs == [r.instructions[-1].result]
        else: assert not r.outputs
    body_region = next(r for r in loop.regions if r.kind=='body')
    assert sum(i.opcode == exit_ for i in instructions(body_region)) == (0 if exit_=='none' else 1)
    assert Program.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()


@pytest.mark.parametrize('language', ['javascript','typescript','java','csharp','cpp'])
def test_omitted_for_parts_have_no_invented_reads_or_updates(language):
    p = program(loop_source(language,'for(;;){break;}'),language)
    loop = p.functions[0].body.instructions[0]
    assert loop.opcode == 'loop',p.format()
    init,test,body,update=loop.regions
    assert init.instructions == update.instructions == []
    assert test.instructions[0].opcode == 'const'
    assert test.instructions[0].attrs['implicit']
    assert test.instructions[0].result_type['kind'] == 'bool'


@pytest.mark.parametrize('language', ['javascript','typescript'])
def test_nullish_coalescing_is_not_boolean_or(language):
    p = program(wrapper(language,'a ?? probe(b)'),language)
    branch = next(i for i in p.functions[0].body.instructions if i.opcode=='short_circuit')
    assert branch.attrs['truth']=='nullish'
    assert branch.attrs['result_policy']=='selected-operand'


@pytest.mark.parametrize('expression', ['x'+'.value'*100, 'probe('*100+'x'+')'*100])
def test_depth_budget_survives_address_and_call_helper_boundaries(expression):
    p = program('def f(x):\n return '+expression+'\n')
    f = p.functions[0]
    assert f.status=='partial'
    assert any('nesting-limit' in r for r in f.reasons)
    assert any(i.opcode=='native' and i.attrs['reason']=='nesting-limit' for i in instructions(f.body))


@pytest.mark.parametrize('expression', ['left()+right()', 'left()<right()', 'left()&&right()'])
def test_cpp_operators_do_not_invent_sequencing_or_builtin_dispatch(expression):
    p = program('int f(){return '+expression+';}', 'cpp')
    f=p.functions[0]
    assert f.status=='partial'
    assert not any(i.opcode=='call' for i in f.body.instructions)
    assert any(i.opcode=='native' and i.attrs['reason']=='operator-evaluation-order' for i in f.body.instructions)
