import pytest
from ken.common_ast import parse
from ken.common_ast.environment import Environment


def refs(program,name):
 return [r for r in program.references if r.name==name and r.mode=='read']


def test_python_nested_scope_and_nonlocal_share_identity():
 p=parse('def outer():\n x=1\n def inner():\n  nonlocal x\n  x=x+1\n  return x\n return x\n','python')
 xs=[s for s in p.symbols if s.name=='x']
 assert len(xs)==1
 assert all(r.symbol==xs[0].id for r in refs(p,'x'))


def test_python_global_directive_targets_module_binding():
 p=parse('x=1\ndef f():\n global x\n x=x+1\n return x\n','python')
 xs=[s for s in p.symbols if s.name=='x']
 assert len(xs)==1 and xs[0].scope==0
 assert all(r.symbol==xs[0].id for r in refs(p,'x'))


def test_python_local_shadow_does_not_fall_back_to_global_before_assignment():
 p=parse('x=1\ndef f():\n print(x)\n x=2\n return x\n','python')
 reads=refs(p,'x')
 assert len(reads)==2 and reads[0].symbol==reads[1].symbol
 assert reads[0].availability=='unavailable' and reads[1].availability=='available'


def test_python_method_lookup_skips_class_namespace():
 p=parse('x=1\nclass C:\n x=2\n def f(self):\n  return x\n','python')
 symbol=p.symbols[refs(p,'x')[0].symbol]
 assert symbol.scope==0


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_let_shadow_is_visible_in_tdz_and_var_is_function_scoped(language):
 p=parse('function f() { let x=1; { use(x); let x=2; use(x); var y=3; } return y; }',language)
 reads=refs(p,'x')
 assert len(reads)==2 and reads[0].symbol==reads[1].symbol
 assert reads[0].availability=='unavailable' and reads[1].availability=='available'
 y=next(s for s in p.symbols if s.name=='y')
 assert p.scopes[y.scope].kind=='callable'
 assert refs(p,'y')[0].symbol==y.id


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_var_initialized_to_undefined_before_initializer(language):
 p=parse('function f() { use(x); var x=1; }',language)
 assert refs(p,'x')[0].availability=='available'


def test_rust_redeclaration_uses_old_binding_in_initializer_and_new_after():
 p=parse('fn f() { let x=1; let x=x+1; use_value(x); }','rust')
 xs=[s for s in p.symbols if s.name=='x']; reads=refs(p,'x')
 assert len(xs)==2 and xs[0].scope==xs[1].scope
 assert [r.symbol for r in reads]==[xs[0].id,xs[1].id]


@pytest.mark.parametrize('language,source',[
 ('python','def f(flag):\n if flag:\n  x=1\n return x\n'),
 ('javascript','function f(flag) { if(flag) { var x=1; } return x; }'),
])
def test_syntax_does_not_prove_conditional_initialization(language,source):
 p=parse(source,language)
 assert refs(p,'x')[-1].availability=='unknown'


@pytest.mark.parametrize('language,source,name',[
 ('python','import os as system\ndef f():\n return system\n','system'),
 ('python','from abc import X as Y\ndef f():\n return Y\n','Y'),
 ('typescript','import {X as Y} from "m"; function f() {return Y;}','Y'),
 ('javascript','import * as ns from "m"; function f() {return ns;}','ns'),
])
def test_import_aliases_are_symbols_not_assumed_external_targets(language,source,name):
 p=parse(source,language)
 imported=next(s for s in p.symbols if s.name==name)
 assert imported.kind=='import' and 'external' in imported.flags
 assert refs(p,name)[-1].symbol==imported.id


@pytest.mark.parametrize('language,source,namespace',[
 ('java','package app.core; class A { int f() {return 1;} }','app.core.A.f'),
 ('go','package core\nfunc f() int {return 1}','core.f'),
 ('cpp','namespace core { class A { int f() {return 1;} }; }','snippet.core.A.f'),
 ('csharp','namespace Core { class A { int f() {return 1;} } }','snippet.Core.A.f'),
 ('rust','struct A {} impl A { fn f() -> i32 {return 1;} }','snippet.A.f'),
])
def test_full_namespace_follows_named_contexts(language,source,namespace):
 p=parse(source,language)
 ret=next(n for n in p.nodes if n.kind=='return')
 assert p.scopes[ret.scope].namespace==namespace


def test_parentheses_do_not_create_a_lexical_scope():
 p=parse('def f(x):\n return (((x)))\n','python')
 assert [s.kind for s in p.scopes]==['module','callable']


def test_comprehension_binding_does_not_escape_python_comprehension():
 p=parse('def f(xs):\n y=[x for x in xs]\n return x\n','python')
 assert refs(p,'x')[-1].status=='unknown'
 assert any(p.scopes[s.scope].kind=='comprehension' for s in p.symbols if s.name=='x')
