"""Instruction contracts are checked on source, not printed graph triples."""
import copy
import json

import pytest

from ken.cli import main
from ken.structural import lower_source, link_project, lower_instructions
from ken.structural.instructions import Program


SOURCES = {
    'python': 'def rename(records, key, new_name):\n item=records[key]\n item.name=new_name\n log(1)\n return item\n',
    'javascript': 'function rename(records,key,new_name){let item=records[key];item.name=new_name;log(1);return item;}',
    'typescript': 'function rename(records:Item[],key:number,new_name:string){let item=records[key];item.name=new_name;log(1);return item;}',
    'java': 'class C{Item rename(Item[] records,int key,String new_name){Item item=records[key];item.name=new_name;log(1);return item;}}',
    'csharp': 'class C{Item rename(Item[] records,int key,string new_name){Item item=records[key];item.name=new_name;log(1);return item;}}',
    'go': 'package p\nfunc rename(records []Item,key int,new_name string) Item {item:=records[key];item.name=new_name;log(1);return item}',
    'rust': 'fn rename(records: Vec<Item>,key:usize,new_name:String)->Item {let mut item=records[key];item.name=new_name;log(1);return item;}',
    'cpp': 'Item rename(Item* records,int key,int new_name){auto item=records[key];item.name=new_name;log(1);return item;}',
}


def program(source, language='python'):
    unit = lower_source(source, language, 'source')
    assert not unit.diagnostics
    return lower_instructions(link_project([unit]))


@pytest.mark.parametrize('language', SOURCES)
def test_lookup_store_update_and_return_are_distinct(language):
    p = program(SOURCES[language], language)
    fn = next(f for f in p.functions if f.name == 'rename')
    instructions = fn.body.instructions
    codes = [i.opcode for i in instructions]
    assert 'index.addr' in codes, p.format()
    assert 'slot.store' in codes and 'memory.store' in codes, p.format()
    store = next(i for i in instructions if i.opcode == 'slot.store')
    assert fn.places[store.operands[0].ref]['name'] == 'item'
    write = next(i for i in instructions if i.opcode == 'memory.store')
    assert write.operands[0].kind == 'value'
    assert 'write.memory' in write.effects and 'write.binding' not in write.effects
    assert codes.index('slot.store') < codes.index('memory.store') < codes.index('call') < codes.index('return')
    assert Program.from_dict(json.loads(json.dumps(p.to_dict()))).to_dict() == p.to_dict()


def test_rebinding_is_an_additional_slot_write():
    p = program(SOURCES['python'].replace(' log(1)', ' item=other\n log(1)'))
    fn = p.functions[0]
    assert len([i for i in fn.body.instructions if i.opcode == 'slot.store']) == 2


@pytest.mark.parametrize('language,source', [
    ('javascript','function f(){let x;return 1;}'),
    ('typescript','function f(){let x:number;return 1;}'),
    ('java','class C {int f(){int x;return 1;}}'),
    ('csharp','class C {int f(){int x;return 1;}}'),
    ('cpp','int f(){int x;return 1;}'),
])
def test_declaration_does_not_invent_a_read_or_write(language, source):
    p = program(source, language)
    instructions = p.functions[0].body.instructions
    assert any(i.opcode == 'slot.declare' for i in instructions), p.format()
    assert not any(i.opcode in {'slot.load','slot.store'} for i in instructions), p.format()


def test_unknown_call_is_not_pure_because_its_name_is_log():
    fn = program(SOURCES['python']).functions[0]
    call = next(i for i in fn.body.instructions if i.opcode == 'call')
    assert call.effects == ['invoke', 'unknown']


def test_branches_keep_writes_in_separate_regions():
    fn = program('def f(x):\n if x:\n  x=1\n else:\n  x=2\n return x\n').functions[0]
    branch = next(i for i in fn.body.instructions if i.opcode == 'if')
    assert [r.kind for r in branch.regions] == ['consequence', 'alternative']
    assert all(any(i.opcode == 'slot.store' for i in r.instructions) for r in branch.regions)
    assert not any(i.opcode == 'slot.store' for i in fn.body.instructions)


def test_while_test_is_a_repeated_region_not_a_precomputed_value():
    fn = program('def f(x):\n while x:\n  x=0\n return x\n').functions[0]
    loop = next(i for i in fn.body.instructions if i.opcode == 'loop')
    assert [r.kind for r in loop.regions] == ['test', 'body']
    assert loop.regions[0].instructions[0].opcode == 'slot.load'
    assert loop.regions[0].outputs == [loop.regions[0].instructions[0].result]


@pytest.mark.parametrize('expression', ['a() < b() < c()', 'f(*args)', 'f(**kwargs)'])
def test_unmodeled_evaluation_is_explicitly_partial(expression):
    fn = program('def f(args,kwargs):\n return '+expression+'\n').functions[0]
    assert fn.status == 'partial' and fn.reasons
    assert any(i.opcode == 'native' and 'unknown' in i.effects for i in fn.body.instructions)


@pytest.mark.parametrize('expression,opcode', [('yield x','yield'), ('yield from x','yield.delegate'), ('await x','await')])
def test_suspension_has_explicit_effects(expression, opcode):
    fn = program(('async ' if opcode == 'await' else '')+'def f(x):\n '+expression+'\n').functions[0]
    insn = next(i for i in fn.body.instructions if i.opcode == opcode)
    assert 'suspend' in insn.effects and 'unknown' in insn.effects


def test_types_preserve_any_unknown_and_container_arguments():
    fn = program('function f(a:any,b:unknown,c:Array<number>){return a;}', 'typescript').functions[0]
    types = [fn.places[p]['type'] for p in fn.parameters]
    assert types[0]['kind'] == 'any' and types[1]['kind'] == 'unknown'
    assert types[2]['arguments'][0]['kind'] in {'number', 'float'}


@pytest.mark.parametrize('language,source', [
    ('rust','fn f(x:i32)->i32 {x}'),
    ('javascript','const f = x => x;'),
    ('typescript','const f = (x:number) => x;'),
    ('python','f = lambda x: x'),
])
def test_implicit_return_is_an_instruction(language, source):
    p = program(source, language)
    fn = p.functions[0]
    assert fn.body.instructions[-1].opcode == 'return', p.format()
    assert fn.body.instructions[-1].attrs['implicit']


@pytest.mark.parametrize('corruption', ['undefined', 'duplicate', 'place', 'opcode', 'result', 'branch-escape'])
def test_verifier_rejects_broken_instruction_programs(corruption):
    p = program('def f(x):\n if x:\n  x=1\n return x\n')
    instructions = p.functions[0].body.instructions
    if corruption == 'undefined': instructions[-1].operands[0].ref = 'missing'
    elif corruption == 'duplicate': instructions.append(copy.deepcopy(instructions[0]))
    elif corruption == 'place': instructions[0].operands[0].ref = 'missing'
    elif corruption == 'opcode': instructions[0].opcode = 'wishful.purity'
    elif corruption == 'result': instructions[-1].result = '%bad'
    else: instructions[-1].operands[0].ref = instructions[1].regions[0].instructions[0].result
    with pytest.raises(ValueError): p.verify()


@pytest.mark.parametrize('format_', ['text', 'json'])
def test_cli_exposes_instruction_ir(tmp_path, capsys, format_):
    (tmp_path/'example.py').write_text(SOURCES['python'])
    assert main(['structural','ir','--path',str(tmp_path),'--view','instructions','--format',format_,'--symbol','rename','--cache-mb','0']) == 0
    output = capsys.readouterr().out
    if format_ == 'json': assert json.loads(output)['ir']['schema'] == 'ken-instructions/1'
    else: assert 'slot.store' in output and 'memory.store' in output and 'func "rename"' in output
