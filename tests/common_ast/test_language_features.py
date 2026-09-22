"""Language differences must survive normalization without inventing semantics."""
import pytest
from ken.common_ast import parse, Program
from ken.common_ast.environment import Environment


def test_python_parameter_separators_receivers_and_packs():
 p=parse('class A:\n def f(self, x, /, y=1, *args, flag=True, **kwargs):\n  return x\n','python')
 params=[s for s in p.symbols if s.kind=='parameter']
 assert [(s.name,s.position,s.native_position,s.parameter_kind) for s in params]==[
  ('self',None,0,'positional_only'),('x',0,1,'positional_only'),('y',1,3,'positional'),
  ('args',2,4,'variadic_positional'),('flag',3,5,'keyword_only'),('kwargs',4,6,'variadic_keyword')]


@pytest.mark.parametrize('language,source,expected',[
 ('python','f(x, *xs, option=y, **kw)', [('positional','',0),('spread_positional','',None),('named','option',None),('spread_named','',None)]),
 ('javascript','f(x, ...xs, y)', [('positional','',0),('spread_positional','',None),('positional','',None)]),
 ('typescript','f(x, ...xs, y)', [('positional','',0),('spread_positional','',None),('positional','',None)]),
 ('csharp','class A {void f(){ g(x, option:y); }}', [('positional','',0),('named','option',None)]),
 ('go','package a\nfunc f(){g(x,xs...)}', [('positional','',0),('spread_positional','',None)]),
])
def test_arguments_preserve_keyword_and_uncertain_expanded_positions(language,source,expected):
 p=parse(source,language)
 args=[n for n in p.nodes if n.argument_kind]
 assert [(n.argument_kind,n.argument_name,n.argument_position) for n in args]==expected
 assert [n.source_position for n in args]==list(range(len(args)))
 assert len([l for l in p.links if l.relation=='argument'])==len(args)
 assert not any(r.name=='option' for r in p.references)


@pytest.mark.parametrize('language,source,expected',[
 ('python','a="hello"\nb=2.5\nc=True\nd=None', {'"hello"':'str','2.5':'float','True':'bool','None':'null'}),
 ('javascript','let a="hello", b=2.5, c=true, d=null, e=0xff;', {'"hello"':'str','2.5':'float','true':'bool','null':'null','0xff':'int'}),
 ('cpp','auto a="hello"; auto b=2.5; auto c=0xff; auto d=\'x\';', {'"hello"':'str','2.5':'float','0xff':'int',"'x'":'char'}),
 ('go','package a\nvar a="hello"\nvar b=2.5\nvar c=\'x\'', {'"hello"':'str','2.5':'float',"'x'":'char'}),
])
def test_literal_payload_and_type_family(language,source,expected):
 p=parse(source,language)
 actual={n.text:n.type_kind for n in p.nodes if n.kind=='literal'}
 assert expected.items()<=actual.items()


def test_interpolation_is_an_expression_not_a_constant():
 p=parse('x=f"hello {name}"','python')
 assert any(n.kind=='interpolated_string' for n in p.nodes)
 assert any(r.name=='name' for r in p.references)


def test_python_defaults_and_comprehension_iterable_use_enclosing_scope():
 p=parse('x=[1]\ndef f(x=x):\n y=[x for x in x]\n return x\n','python')
 xs=[s for s in p.symbols if s.name=='x']
 assert len(xs)==3
 reads=[r for r in p.references if r.name=='x']
 assert [r.symbol for r in reads]==[xs[0].id,xs[2].id,xs[1].id,xs[1].id]


@pytest.mark.parametrize('directive',['global','nonlocal'])
def test_directives_survive_serialization_and_keep_execution_boundary(directive):
 source='x=1\ndef f():\n global x\n return x\n' if directive=='global' else 'def f():\n x=1\n def g():\n  nonlocal x\n  return x\n'
 p=Program.from_dict(parse(source,'python').to_dict())
 ref=next(r for r in p.references if r.name=='x')
 env=Environment(p.scopes,p.symbols,language=p.language)
 found=env.resolve(ref.name,ref.scope,p.nodes[ref.node].start)
 assert found.symbol==ref.symbol and found.status=='known'
 assert found.availability==ref.availability=='unknown'


def test_invalid_nonlocal_does_not_resolve_module_variable():
 p=parse('x=1\ndef f():\n nonlocal x\n return x\n','python')
 assert next(r for r in p.references if r.name=='x').status=='unknown'


@pytest.mark.parametrize('source',[
 'def f():\n x=1\n del x\n return x\n',
 'def f():\n x=1\n exec("del x")\n return x\n',
])
def test_dynamic_effects_do_not_certify_initialization(source):
 p=parse(source,'python')
 assert [r for r in p.references if r.name=='x'][-1].availability=='unknown'


@pytest.mark.parametrize('language,source,names',[
 ('rust','use std::{io, fmt::Debug as D}; fn f() {io::f(); D::f();}',{'io','D'}),
 ('csharp','using X = System.Text.StringBuilder; using System; class A {}',{'X'}),
 ('go','package a\nimport x "thing/custom"\nfunc f(){g(x.V)}',{'x'}),
])
def test_import_forms(language,source,names):
 p=parse(source,language)
 assert {s.name for s in p.symbols if s.kind=='import'}==names
 if language=='rust':
  assert all(r.status=='unknown' for r in p.references if r.name=='f')


def test_go_default_package_name_is_not_guessed_from_import_path():
 p=parse('package a\nimport "example.com/strange-name/v2"\nfunc f(){actual.F()}','go')
 assert next(r for r in p.references if r.name=='actual').status=='unknown'
 assert not any(r.name=='a' for r in p.references)


@pytest.mark.parametrize('language,source',[
 ('python','def f():\n try:\n  g()\n except E:\n  h()\n finally:\n  k()\n'),
 ('javascript','function f(){try {g();} catch(e){h();} finally{k();}}'),
 ('java','class A {void f(){try{g();} catch(Exception e){h();} finally{k();}}}'),
 ('csharp','class A {void f(){try{g();} catch(Exception e){h();} finally{k();}}}'),
 ('cpp','void f(){try{g();} catch(E e){h();}}'),
 ('ruby','def f\n begin\n g\n rescue E\n h\n ensure\n k\n end\nend'),
])
def test_exception_regions_preserve_structure(language,source):
 p=parse(source,language)
 assert {'try','catch'}<={n.kind for n in p.nodes}
 if language!='cpp': assert any(n.kind=='finally' for n in p.nodes)


def test_ruby_block_parameters_shadow_outer_locals():
 p=parse('x=0\nxs.each do |x|\n puts x\nend\nputs x','ruby')
 xs=[s for s in p.symbols if s.name=='x']
 reads=[r for r in p.references if r.name=='x']
 assert len(xs)==2 and [r.symbol for r in reads]==[xs[1].id,xs[0].id]
 assert p.scopes[xs[1].scope].kind=='callable'


def test_resource_alias_shadows_outer_function():
 p=parse('def f():\n with open("f") as f:\n  return f\n','python')
 ref=next(r for r in p.references if r.name=='f')
 assert p.symbols[ref.symbol].kind=='variable'
 assert p.scopes[p.symbols[ref.symbol].scope].kind=='callable'


def test_async_block_is_a_distinct_execution_context():
 p=parse('async fn f() {let x=1; let y=async {consume(x).await;};}','rust')
 ref=next(r for r in p.references if r.name=='x')
 assert ref.status=='known' and ref.availability=='unknown'
 assert any(s.kind=='deferred_block' for s in p.scopes)
 assert {'deferred_block','await'}<={n.kind for n in p.nodes}


def test_go_concurrency_syntax_is_preserved_without_happens_before_claims():
 p=parse('package a\nfunc f(ch chan int){go work(); defer cleanup(); ch <- 1; select {case ch <-2: default:}}','go')
 assert {'spawn','defer','send','select','select_arm'}<={n.kind for n in p.nodes}
 assert not any(l.relation=='happens_before' for l in p.links)


@pytest.mark.parametrize('language,source,types',[
 ('typescript','function f(a:any,b:unknown,c:string,d:boolean){return a;}', {'a':'any','b':'unknown','c':'str','d':'bool'}),
 ('python','def f(a: int, b: str, c: float, d: list[int], e: dict[str,int]):\n return a\n', {'a':'int','b':'str','c':'float','d':'list','e':'map'}),
 ('rust','fn f(a:i32,b:f64,c:char,d:bool){}', {'a':'int','b':'float','c':'char','d':'bool'}),
])
def test_basic_parameter_type_families(language,source,types):
 p=parse(source,language)
 assert types.items()<={s.name:s.type_kind for s in p.symbols if s.kind=='parameter'}.items()
