"""Native graph compilation, conservative evidence and snapshot reuse."""
import json

import pytest

from ken.kql2.compiler import compile, CompileError
from ken.kql2.syntax import parse
from ken.kql2.graph import relational_plan
from ken.kql2.execution import execute
from ken.kql2.compilation import Prepared
from ken.kql2.codec import encode, decode
from ken.structural.relational import Executor
from ken.structural.model import IR, Fact, FactIndex, Entity
from ken.structural.frontend import lower_source
from ken.structural_store import Store

HEADER = 'language "kql/2"; module example; '


def program(source):
    return compile(parse(HEADER + source))


def run(source, facts, *, possible=False, capabilities=()):
    graph = IR('example.py', 'python', facts=facts, capabilities=set(capabilities))
    return Executor(FactIndex(graph), {}, evidence_mode='possible' if possible else 'strict').execute(relational_plan(program(source)))


@pytest.mark.parametrize('matcher,expected', [
    ('"a|b"', ['pipe']), ('["a", "b"]', ['a','b']), ('/^a$/i', ['a']),
    ('"missing"', []), ('false', ['false']), ('0', ['zero']),
])
def test_context_literals_lists_regex_and_falsy_values(matcher, expected):
    values = [('pipe','a|b'), ('a','a'), ('b','b'), ('false',False), ('zero',0), ('none',None)]
    facts = [Fact(key, 'ENTITY', 'CLASS', {'name':value}) for key,value in values]
    result = run('query q { edge ENTITY($x, "CLASS") { name: '+matcher+'; }; select $x; }', facts)
    assert result['complete']
    assert sorted(m['bindings']['$x'] for m in result['matches']) == expected


def test_named_patterns_correlate_inputs_and_keep_local_witnesses_hygienic():
    result = run('''
        pattern children(in GraphTerm $parent, out GraphTerm $child) { edge HAS_METHOD($parent, $child); }
        query q {
          edge ENTITY($p, "CLASS");
          use children(parent:$p, child:$a);
          use children(parent:$p, child:$b);
          where $a != $b;
          select $p, $a, $b;
        }
    ''', [Fact('p','ENTITY','CLASS'), Fact('p','HAS_METHOD','a'), Fact('p','HAS_METHOD','b'), Fact('other','HAS_METHOD','c')])
    assert {tuple(m['bindings'].values()) for m in result['matches']} == {('p','a','b'),('p','b','a')}


def test_bind_alias_seed_pushes_to_original_role():
    p = program('''pattern same(out GraphTerm $a, out GraphTerm $b) { edge ENTITY($a,"CLASS"); bind $b = $a; }
      query q { edge HAS_METHOD("owner", $x); use same(b:$x, a:$y); select $x,$y; }''')
    plan = relational_plan(p)
    assert any(q.exports == {'a':'$a','b':'$a'} for q in plan.definitions.values())
    facts = [Fact('owner','HAS_METHOD','found'), Fact('found','ENTITY','CLASS'), Fact('other','ENTITY','CLASS')]
    out = Executor(FactIndex(IR('x','python',facts=facts)),{}).execute(plan)
    assert [m['bindings'] for m in out['matches']] == [{'$x':'found','$y':'found'}]


def test_large_alternative_products_stay_grouped_and_roundtrip_codec():
    body = '\n'.join(f'either {{ edge ENTITY($v{i},"CLASS"); }} or {{ edge ENTITY($v{i},"INTERFACE"); }}' for i in range(12))
    p = program('query q {'+body+' select $v0; }')
    assert p.graph and not p.branches
    prepared = Prepared(p, ((p.fingerprint, ()),))
    assert decode(encode(prepared), max_bytes=1_000_000) == prepared
    assert len(relational_plan(p).nodes) == 12


@pytest.mark.parametrize('source,reason', [
    ('query q { edge MADE_UP($a,$b); select $a; }', 'unknown graph relation'),
    ('query q { edge ENTITY($a,"CLASS"); select $b; }', 'not bound'),
    ('query q { either { edge ENTITY($a,"CLASS"); } or { edge ENTITY($b,"CLASS"); } select $a; }', 'not bound'),
    ('query q { walk CFG_NEXT($a,$b) {min:0;max:33;} as $p; select $a; }', 'bounds'),
    ('query q { tally distinct $w >= 1 {edge ENTITY($a,"CLASS");}; select $a; }', 'witness'),
    ('query q { edge ENTITY($a,"CLASS"); bind $a=$a; select $a; }', 'fresh'),
    ('query q { edge ENTITY($a,"CLASS"); where $b == $a; select $a; }', 'bound'),
    ('pattern p(in GraphTerm $x,out GraphTerm $y) {edge TYPE($x,$y);} query q {use p(x:$x,y:$y); select $y;}', 'input'),
    ('pattern p(out GraphTerm $x) {edge ENTITY($x,"CLASS"); use p(x:$x);} query q {use p(x:$x);select $x;}', 'recursive'),
])
def test_invalid_graph_plans_fail_before_io(source, reason):
    with pytest.raises(CompileError, match=reason):
        program(source)


@pytest.mark.parametrize('minimum,maximum,expected', [(0,0,{('a','a'),('b','b')}),(1,1,{('a','b'),('b','a')}),(2,2,{('a','a'),('b','b')})])
def test_walk_cycles_zero_length_and_bounds(minimum, maximum, expected):
    q=f'query q {{ walk CFG_NEXT($a,$b) {{min:{minimum};max:{maximum};}} as $path; select $a,$b; }}'
    out=run(q,[Fact('a','CFG_NEXT','b'),Fact('b','CFG_NEXT','a')])
    assert {tuple(m['bindings'].values()) for m in out['matches']} == expected


@pytest.mark.parametrize('explicit,mode,expected', [(False,False,False),(False,True,True),(True,False,True)])
def test_possible_edges_preserve_uncertainty(explicit,mode,expected):
    context='{modality:"may";}' if explicit else ''
    out=run(f'query q {{edge TARGET($a,$b) {context};select $a;}}',[Fact('a','TARGET','b',{'modality':'may'})],possible=mode)
    assert bool(out['matches']) == expected
    if mode:
        assert out['matches'][0]['status'] == 'unknown'
    elif not explicit:
        assert out['unknown'] == ['possible:TARGET']


@pytest.mark.parametrize('closed,comparison,match,unknown', [(False,'>= 1',True,False),(False,'== 1',False,True),(True,'== 1',True,False)])
def test_exact_tally_needs_closure_but_lower_bound_can_use_witness(closed,comparison,match,unknown):
    out=run('query q {edge ENTITY($p,"CLASS"); tally distinct $m '+comparison+' {edge HAS_METHOD($p,$m);}; select $p;}',
            [Fact('p','ENTITY','CLASS'),Fact('p','HAS_METHOD','m')],capabilities=['complete:p:HAS_METHOD'] if closed else [])
    assert bool(out['matches']) == match
    assert bool(out['unknown']) == unknown


def test_snapshot_graph_disk_reopen_without_linking_or_loading_units(tmp_path, monkeypatch):
    p = program('query q {edge ENTITY($c,"CLASS"); select $c;}')
    db = tmp_path/'graph.sqlite'
    with Store(db, cache_mb=20) as store:
        ir = lower_source('class Widget:\n pass\n','python','widget.py')
        unit = store.put_unit('unit',ir,'hash','frontend')
        snapshot = store.publish([unit],expected_parent=None)
        first = execute(p,store,snapshot)
        assert first.rows and not first.plan[0]['graph_disk_hit']
    with Store(db, cache_mb=20) as store:
        def forbidden(*args,**kwargs): raise AssertionError('warm graph must be read directly')
        monkeypatch.setattr('ken.kql2.graph_execution.link_project',forbidden)
        monkeypatch.setattr(store,'load_unit',forbidden)
        second = execute(p,store,snapshot)
        assert second.rows == first.rows and second.plan[0]['graph_disk_hit']


def test_native_execution_does_not_enter_legacy_parser(tmp_path, monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError('legacy parser entered')
    monkeypatch.setattr('ken.structural.kenql.Parser',forbidden)
    with Store() as store:
        ir=lower_source('class Widget:\n pass\n','python','widget.py')
        u=store.put_unit('u',ir,'h','f');snapshot=store.publish([u],expected_parent=None)
        p=program('query q {edge ENTITY($c,"CLASS");select $c;}')
        assert execute(p,store,snapshot).rows
        assert execute(p,store,snapshot,cancelled=lambda:True).reason == 'cancelled'
        assert not execute(p,store,snapshot,max_states=1).complete
        assert execute(p,store,snapshot,timeout_ms=0).reason == 'timeout_ms'


def test_packaged_pattern_import_through_public_service_and_disk_cache(tmp_path, monkeypatch):
    from ken.kql2.service import search
    from ken.kql2.compilation import clear_compilation_cache
    (tmp_path/'builder.py').write_text('''class Product:
 def __init__(self, x): self.x = x
class Subject:
 def size(self, x): self.x = x
 def finish(self): return Product(self.x)
''')
    source='''language "kql/2"; module example;
      import ken.catalog.builder;
      query builders {use ken.catalog.builder.detect(builder:$builder);select $builder;}'''
    from ken.kql2 import catalog
    original_sources = catalog.sources
    captures = []
    def capture_once():
        captures.append(True)
        assert len(captures) == 1, 'one immutable catalog capture per request'
        return original_sources()
    monkeypatch.setattr(catalog, 'sources', capture_once)
    first=search(tmp_path,source,cache_mb=20)
    assert first['complete'] and first['rows'] and first['columns']==['builder']
    clear_compilation_cache()
    captures.clear()
    second=search(tmp_path,source,cache_mb=20)
    assert second['rows']==first['rows']
    assert second['complete']


def test_saved_rule_accepts_source_selectors():
    from ken.structural.rules import SavedRule
    SavedRule('example',HEADER+'query q {class $x {} select $x;}',query_language='kql/2').validate()


def test_catalog_plan_cache_is_immutable_and_library_text_invalidates_it():
    from ken.kql2.catalog import compile_source
    source=HEADER+'import library.p; query q {use library.p.pick(x:$x);select $x;}'
    def snapshot(kind):
        library=f'language "kql/2"; module library.p; pattern pick(out GraphTerm $x) {{edge ENTITY($x,"{kind}");}}'
        return (('library.toml', 'query = '+json.dumps(library)),)
    first=compile_source(source,snapshot=snapshot('CLASS'))
    second=compile_source(source,snapshot=snapshot('INTERFACE'))
    with pytest.raises(TypeError):
        first.exports['x']='changed'
    index=FactIndex(IR('x','python',facts=[Fact('class','ENTITY','CLASS'),Fact('interface','ENTITY','INTERFACE')]))
    assert [m['bindings'] for m in Executor(index,{}).execute(first)['matches']]==[{'$x':'class'}]
    assert [m['bindings'] for m in Executor(index,{}).execute(second)['matches']]==[{'$x':'interface'}]
