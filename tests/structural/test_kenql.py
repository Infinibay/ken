from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from ken.structural.kenql import Engine, parse, query_graph
from ken.structural.model import FactIndex, IR, Entity
from ken.structural.query import QueryBudget
from ken.structural.rules import SavedRule, execute_rules, read_rules
from ken.structural.service import search


def graph(*edges):
    ir = IR('test', 'mixed')
    for a, r, b in edges:
        ir.add(a, r, b)
    return ir


def execute(ir, source, library=None, budget=None):
    return Engine(FactIndex(ir), {k: parse(v) for k, v in (library or {}).items()}, budget, evidence_mode="possible").execute(parse(source))


PAIR = 'query pairs { require $f MAKES $p; emit factory=$f, product=$p; }'


def test_named_query_preserves_correlated_roles():
    ir = graph(('A','MAKES','X'), ('B','MAKES','Y'), ('A','NEEDS','Y'))
    q = '''query use_pairs {
      match "pairs"(factory: $f, product: $p) as $proof;
      require $f NEEDS $p;
      emit $f, $p;
    }'''
    assert execute(ir, q, {'pairs': PAIR})['matches'] == []


def test_names_inside_named_query_do_not_capture_caller_bindings():
    ir = graph(('A','MAKES','X'), ('root','PARENT','A'))
    q = '''query caller {
      require $f PARENT $factory;
      match "pairs"(factory: $factory, product: $product);
      emit root=$f, $factory, $product;
    }'''
    hit = execute(ir, q, {'pairs': PAIR})['matches'][0]
    assert hit['bindings'] == {'$root':'root', '$factory':'A', '$product':'X'}
    assert hit['evidence'][-1]['query'] == 'pairs'


@pytest.mark.parametrize('prebind', [True, False])
def test_bound_role_pushdown_matches_unbound_join(prebind):
    ir = graph(('A','MAKES','X'), ('A','MAKES','Y'), ('B','MAKES','Z'), ('root','SELECT','A'))
    clauses = ['require _ SELECT $f;', 'match "pairs"(factory: $f, product: $p);']
    if not prebind: clauses.reverse()
    hits = execute(ir, 'query test {'+' '.join(clauses)+' emit $f,$p;}', {'pairs': PAIR})['matches']
    assert {tuple(h['bindings'].values()) for h in hits} == {('A','X'),('A','Y')}


def test_omitted_exports_are_existential_and_not_duplicate_rows():
    ir = graph(('A','MAKES','X'),('A','MAKES','Y'))
    hits = execute(ir, 'query test { match "pairs"(factory: $f); emit $f; }', {'pairs':PAIR})['matches']
    assert len(hits) == 1


def test_same_caller_binding_for_two_exports_requires_equality():
    ir = graph(('A','MAKES','X'),('B','MAKES','B'))
    hits = execute(ir, 'query q { match "pairs"(factory: $same, product: $same); emit $same; }', {'pairs':PAIR})['matches']
    assert [h['bindings'] for h in hits] == [{'$same':'B'}]


def test_composition_multiple_levels_and_shared_dependency():
    ir = graph(('A','MAKES','X'))
    library = {'pairs':PAIR, 'middle':'query m { match "pairs"(factory:$f, product:$p); emit $f,$p; }'}
    hits = execute(ir, 'query top { match "middle"(f:$f,p:$p); match "pairs"(factory:$f,product:$p); emit $f,$p; }', library)
    assert len(hits['matches']) == 1
    assert hits['stats']['dependencies'] == ['middle','pairs']


@pytest.mark.parametrize('library,query,error', [
    ({}, 'query q { match "missing"(factory:$f); emit $f; }', 'unknown named'),
    ({'pairs':PAIR}, 'query q { match "pairs"(typo:$f); emit $f; }', 'unknown export'),
    ({'a':'query a { match "a"(f:$f); emit $f; }'}, 'query q { match "a"(f:$f); emit $f; }', 'cycle'),
    ({'a':'query a { match "b"(f:$f); emit $f; }','b':'query b { match "a"(f:$f); emit $f; }'}, 'query q { match "a"(f:$f); emit $f; }', 'cycle'),
])
def test_dependency_validation(library, query, error):
    with pytest.raises(ValueError, match=error): execute(graph(),query,library)


@pytest.mark.parametrize('source', [
    'query q { emit $missing; }',
    'query q { callable() as $f; }',
    'query q { callable(typo: true) as $f; emit $f; }',
    'query q { callable(name: []) as $f; emit $f; }',
    'query q { callable(name: /(?=a)/) as $f; emit $f; }',
    'query q { callable(name: /(a)\\1/) as $f; emit $f; }',
    'query q { match "p"(x:$x,x:$y); emit $x; }',
    'query q { any { require $x A $y; } emit $x; }',
    'query q { any { require $x A $y; } or { require $x B $z; } emit $y; }',
    'query q { optional { require $x A $y; } emit $x; }',
    'query q { require $x A $y; not exists {require $x B $z;} within callable($missing); emit $x; }',
    'query q { require $x A $y; different $x $z; emit $x; }',
    'query q { require $x A $y; where $z.name == $x.name; emit $x; }',
    'query q { path $x A{0,33} $y as $p; emit $x; }',
    'query q { path $x A* $y as $p; emit $x; }',
    'query q { require $x A $y; emit $x; } trailing',
])
def test_rejects_invalid_queries(source):
    with pytest.raises(ValueError): parse(source)


def test_any_deduplicates_projection():
    ir = graph(('a','A','b'), ('a','B','c'))
    result=execute(ir,'query q { any { require $x A $y; } or { require $x B $y; } emit $x; }')
    assert len(result['matches'])==1


def test_optional_preserves_match_and_does_not_expand_rows():
    ir=graph(('a','A','b'),('a','B','c'),('a','B','d'))
    result=execute(ir,'query q { require $x A $y; optional {require $x B $z;} emit $x; }')
    assert len(result['matches'])==1
    assert len(result['matches'][0]['evidence'])==3


@pytest.mark.parametrize('closed,expected',[(False,'unknown'),(True,'structural_match')])
def test_absence_requires_scoped_closure(closed,expected):
    ir=graph(('a','ENTITY','CALLABLE'))
    if closed: ir.capabilities.add('complete:a:RELEASES')
    result=execute(ir,'query q { callable() as $f; not exists {require $f RELEASES _;} within callable($f); emit $f; }')
    assert result['matches'][0]['status']==expected


def test_global_syntax_capability_does_not_close_absence():
    ir=graph(('a','ENTITY','CALLABLE'));ir.capabilities.add('syntax')
    result=execute(ir,'query q { callable() as $f; not exists {require $f RELEASES _;} within callable($f); emit $f; }')
    assert result['matches'][0]['unknown']


def test_count_distinct_is_correlated_with_named_query():
    ir=graph(('A','MAKES','X'),('B','MAKES','X'),('A','MAKES','Y'))
    q='''query q {
      require _ MAKES $p;
      count distinct $f >= 2 {match "pairs"(factory:$f,product:$p);};
      emit $p;
    }'''
    assert [h['bindings'] for h in execute(ir,q,{'pairs':PAIR})['matches'] if h['status']=='structural_match']==[{'$p':'X'}]


@pytest.mark.parametrize('lo,hi,expected',[(0,0,{'a'}),(0,2,{'a','b','c'}),(1,2,{'b','c'}),(2,2,{'c'})])
def test_explicit_path_bounds(lo,hi,expected):
    ir=graph(('root','SELECT','a'),('a','LINK','b'),('b','LINK','c'),('c','LINK','a'))
    result=execute(ir,f'query q {{ require _ SELECT $a; path $a LINK{{{lo},{hi}}} $b as $w; emit $b; }}')
    assert {h['bindings']['$b'] for h in result['matches']}==expected


def test_zero_path_on_isolated_entity():
    ir=graph(('root','SELECT','a')); ir.relations.add('LINK')
    result=execute(ir,'query q { require _ SELECT $a; path $a LINK{0,0} $b as $w; emit $b; }')
    assert result['matches'][0]['bindings']=={'$b':'a'}


@pytest.mark.parametrize('budget',[QueryBudget(max_states=2),QueryBudget(max_rows=1),QueryBudget(max_matches=1)])
def test_budgets_apply_to_dependencies(budget):
    ir=graph(('A','MAKES','X'),('B','MAKES','Y'))
    result=execute(ir,'query q { match "pairs"(factory:$f); emit $f; }',{'pairs':PAIR},budget)
    assert not result['complete']
    assert any(x.startswith('budget:') for x in result['unknown'])


def test_where_compares_entity_properties():
    ir=graph(('a','ENTITY','CALLABLE'),('b','ENTITY','CALLABLE'))
    ir.entities={x:Entity(x,'CALLABLE',x,'f.py',1,1) for x in 'ab'}
    result=execute(ir,'query q { callable() as $f; where $f.name == "b"; emit $f; }')
    assert [h['bindings'] for h in result['matches']]==[{'$f':'b'}]


def test_custom_toml_named_query_on_source(tmp_path):
    folder=tmp_path/'.ken/rules'; folder.mkdir(parents=True)
    (folder/'public.toml').write_text('id = "team.public"\nquery = \'\'\'query public { function(name: /^public/) as $f; emit function=$f; }\'\'\'\n')
    (tmp_path/'a.py').write_text('def public_one(): return 1\ndef private_one(): return 2\n')
    result=search(tmp_path,'query q { match "team.public"(function:$f); emit $f; }',cache_mb=0)
    assert len(result['matches'])==1
    assert result['matches'][0]['path']=='a.py'


def test_dependency_error_happens_before_scan(tmp_path):
    with pytest.raises(ValueError,match='unknown named'):
        search(tmp_path,'query q { match "typo"(function:$f); emit $f; }')
    assert not (tmp_path/'.ken').exists()


def test_argument_occurrences_do_not_collapse_repeated_value():
    ir=IR('test','mixed')
    ir.add('call','ARGUMENT','same',position=0)
    ir.add('call','ARGUMENT','same',position=1)
    index=query_graph(ir)
    assert {f.object for f in index.rows('ARGUMENT')}=={'call/argument/0','call/argument/1'}
    assert len(index.rows('VALUE'))==2
    assert all(f.object=='same' for f in ir.facts)


def test_runtime_catalog_is_external_and_retains_variant_designs():
    directory=Path(__file__).parents[2]/'src/ken/structural/patterns'
    files=list(directory.glob('*.toml'))
    assert len(files)==23
    total=0
    for path in files:
        data=tomllib.loads(path.read_text())
        assert data['query'] and data['claim']=='structural-signature'
        total+=len(data['variants'])
    assert total>=60


@pytest.mark.parametrize('language,suffix,source,variant', [
    ('python','.py','def items():\n yield 1\n','generator'),
    ('python','.py','def items(xs):\n yield from xs\n','delegated-generator'),
    ('javascript','.js','function* items() { yield 1; }','generator'),
    ('javascript','.js','function* items(xs) { yield* xs; }','delegated-generator'),
    ('typescript','.ts','function* items(): Generator<number> { yield 1; }','generator'),
    ('typescript','.ts','function* items(xs: number[]) { yield* xs; }','delegated-generator'),
    ('csharp','.cs','class Items { System.Collections.Generic.IEnumerable<int> Values() { yield return 1; } }','generator'),
])
def test_generator_variants_on_real_languages(tmp_path,language,suffix,source,variant):
    (tmp_path/('sample'+suffix)).write_text(source)
    result=search(tmp_path,f'query q {{ match "gof.iterator#{variant}"(iterator:$i); emit $i; }}',cache_mb=0)
    assert result['analysis']['coverage_complete'],result['analysis']
    assert len(result['matches'])==1,result


def test_typescript_unknown_is_known_annotation_not_missing_analysis(tmp_path):
    (tmp_path/'sample.ts').write_text('function explicit(x: unknown): unknown { return x; }\nfunction implicit(x) { return x; }')
    query='query q { parameter(native_type: "unknown", type_state: known) as $p; emit $p; }'
    result=search(tmp_path,query,cache_mb=0)
    assert len(result['matches'])==1


def test_function_selector_excludes_methods(tmp_path):
    (tmp_path/'sample.py').write_text('def free(): pass\nclass C:\n def member(self): pass\n')
    a=search(tmp_path,'query q { function() as $f; emit $f; }',cache_mb=0)
    b=search(tmp_path,'query q { method() as $m; emit $m; }',cache_mb=0)
    assert len(a['matches'])==len(b['matches'])==1
    assert a['matches'][0]['bindings']['$f']!=b['matches'][0]['bindings']['$m']


def test_same_named_query_reload_after_file_edit(tmp_path):
    folder=tmp_path/'.ken/rules';folder.mkdir(parents=True)
    rule=folder/'selected.toml'
    (tmp_path/'a.py').write_text('def one(): pass\ndef two(): pass\n')
    for name in ['one','two']:
        rule.write_text('id="team.selected"\nquery=\'\'\'query q { function(name: "'+name+'") as $f; emit $f; }\'\'\'')
        result=search(tmp_path,'query q { match "team.selected"(f:$f); emit $f; }')
        assert f'CALLABLE:{name}@' in result['matches'][0]['bindings']['$f']


def test_save_creates_independent_visible_toml_and_overwrite(tmp_path):
    from ken.structural.rules import save_rule, load_rules
    rule=SavedRule('team.rule','query q { callable() as $f; emit $f; }',description='Quote " and newline\n')
    path=save_rule(tmp_path,rule)
    assert path==tmp_path/'.ken/rules/team.rule.toml'
    assert tomllib.loads(path.read_text())['description']==rule.description
    with pytest.raises(ValueError,match='already exists'):save_rule(tmp_path,rule)
    rule.description='updated'
    save_rule(tmp_path,rule,overwrite=True)
    assert next(r for r in load_rules(tmp_path) if r.id==rule.id).description=='updated'


def test_strict_filters_unknown_but_reports_reason():
    ir=graph(('a','ENTITY','CALLABLE'))
    q=parse('query q { callable() as $f; not exists {require $f RELEASES _;} within callable($f); emit $f; }')
    result=Engine(FactIndex(ir),{}).execute(q)
    assert result['complete'] and not result['matches']
    assert result['unknown']==['absence:callable:a']


def test_absence_does_not_use_another_callable_release():
    ir=graph(('a','ENTITY','CALLABLE'),('b','RELEASES','lock'))
    ir.capabilities.add('complete:a:RELEASES')
    result=execute(ir,'query q { callable() as $f; not exists {require _ RELEASES _;} within callable($f); emit $f; }')
    assert result['matches'][0]['status']=='structural_match'


def test_canonical_iterator_unions_cursor_and_generator(tmp_path):
    (tmp_path/'a.py').write_text('''
def items():
    yield 1
class Cursor:
    def __iter__(self): return self
    def __next__(self):
        self.position = self.position + 1
        return self.position
''')
    result=search(tmp_path,rule_ids=['gof.iterator'],cache_mb=0)
    assert len(result['matches'])==2
    assert all('$iterator' in h['bindings'] for h in result['matches'])


def test_mutable_builder_tracks_field_into_returned_product(tmp_path):
    (tmp_path/'a.py').write_text('''
class Product:
    def __init__(self, size): self.size = size
class Builder:
    def size(self, size): self.value = size; return self
    def finish(self): return Product(self.value)
class NotBuilder:
    def size(self, size): self.value = size; return self
    def finish(self):
        unused = Product(self.value)
        return Product(123)
''')
    result=search(tmp_path,rule_ids=['gof.builder#mutable-product'],cache_mb=0)
    assert len(result['matches'])==1
    assert '/CLASS:Builder' in result['matches'][0]['bindings']['$builder']


def test_named_query_role_kind_mismatch_is_error():
    query='query q { type_decl() as $type; match "functions"(f:$type); emit $type; }'
    library={'functions':'query f { callable() as $f; emit $f; }'}
    with pytest.raises(ValueError,match='incompatible role kinds'): execute(graph(),query,library)


def test_product_flow_named_factory_on_real_source(tmp_path):
    (tmp_path/'a.py').write_text('''
class Product: pass
class Base:
    def make(self): pass
class Factory(Base):
    def make(self): return Product()
def consume(x): return x
factory: Factory = Factory()
consume(factory.make())
''')
    result=search(tmp_path,'''query product_flow {
 match "gof.factory-method"(factory:$factory, product:$product);
 call() as $creation;
 require $creation TARGET $factory;
 require $creation RESULT $value;
 call() as $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $value;
 emit $factory, $creation, $consumer;
}''',cache_mb=0)
    assert len(result['matches'])==1,result


def test_count_does_not_borrow_another_subjects_completeness():
    ir=graph(('root','SELECT','B'),('root','OTHER','A'))
    ir.capabilities.add('complete:A:HAS_PARAMETER')
    result=execute(ir,'query q { require _ SELECT $b; require _ OTHER $a; count distinct $p = 0 {require $b HAS_PARAMETER $p;}; emit $b; }')
    assert result['matches'][0]['status']=='unknown'


def test_qualified_builtin_id_cannot_be_shadowed(tmp_path):
    folder=tmp_path/'.ken/rules';folder.mkdir(parents=True)
    (folder/'bad.toml').write_text('id="gof.factory-method"\nquery="require $x IS CLASS"')
    with pytest.raises(ValueError,match='duplicate rule id'):
        search(tmp_path,'query q { callable() as $f; emit $f; }',cache_mb=0)


@pytest.mark.parametrize('language', ['javascript','typescript','java','csharp','cpp'])
def test_named_factory_query_uses_multilingual_frontends(language,tmp_path):
    from .examples import MULTILINGUAL
    suffix,source=MULTILINGUAL[language]
    (tmp_path/('example'+suffix)).write_text(source)
    result=search(tmp_path,'query q { match "gof.factory-method"(creator:$creator, factory:$factory, product:$product); emit $creator,$factory,$product; }',cache_mb=0)
    assert result['analysis']['coverage_complete']
    assert result['matches']


@pytest.mark.parametrize('language', ['python','javascript','typescript','java','csharp','cpp','go','rust'])
def test_named_fluent_shape_across_eight_languages(language,tmp_path):
    from .examples import MULTILINGUAL,PYTHON
    suffix,source=('.py',PYTHON['builder']) if language=='python' else MULTILINGUAL[language]
    (tmp_path/('example'+suffix)).write_text(source)
    # Compatibility shape is deliberately separate from the stronger product rule.
    result=search(tmp_path,'query q { match "legacy.gof.builder"(unit:$builder); emit $builder; }',cache_mb=0)
    assert result['analysis']['coverage_complete']
    assert result['matches']


def test_typo_relation_fails_before_scan(tmp_path):
    with pytest.raises(ValueError,match='unknown graph relation'):
        search(tmp_path,'query q { require $f RETRUNS_NEW $p; emit $f; }')
    assert not (tmp_path/'.ken').exists()


def test_custom_relation_schema_survives_serialization():
    ir=graph();ir.relations.add('CUSTOM_RELATION')
    restored=IR.from_dict(ir.to_dict())
    assert execute(restored,'query q { require $a CUSTOM_RELATION $b; emit $a; }')['complete']


@pytest.mark.parametrize('data', [
    {'version':True,'rules':[]},
    {'version':1,'rules':[{'id':'x','query':'require $x IS CLASS','variants':'bad'}]},
    {'version':1,'rules':[{'id':'x','query':'require $x IS CLASS','source':3}]},
    {'version':1,'rules':[{'id':'x','query':'require $x IS CLASS','variants':[{'id':'a','status':'ready'}]}]},
])
def test_invalid_rule_library_rejected(tmp_path,data):
    p=tmp_path/'bad.json';p.write_text(json.dumps(data))
    with pytest.raises(ValueError):read_rules(p)


def test_query_view_round_trip_does_not_rewrap_arguments(tmp_path):
    from ken.structural.service import build_project
    (tmp_path/'a.py').write_text('def call(x): return x\ncall(1)\n')
    ir,_=build_project(tmp_path,cache_mb=0)
    view=query_graph(ir).ir
    assert view.view=='query'
    reloaded=IR.from_dict(view.to_dict())
    assert query_graph(reloaded).ir.to_dict()==view.to_dict()


def test_call_result_and_argument_load_are_distinct_entities(tmp_path):
    from ken.structural.service import build_project
    (tmp_path/'a.py').write_text('def make(): return 1\ndef use(x): return x\nx = make()\nuse(x)\n')
    ir,_=build_project(tmp_path,cache_mb=0)
    view=query_graph(ir)
    result_edges=view.rows('RESULT')
    assert result_edges and all(f.subject != f.object for f in result_edges)
    loads=view.rows('LOADED_FROM')
    assert loads and all(view.ir.entities[f.subject].kind=='VALUE' for f in loads)
    flows=view.rows('VALUE_FLOW')
    assert flows and all(f.attrs.get('modality')=='may' for f in flows)


def test_public_evaluate_query_api(tmp_path):
    from ken.structural import evaluate_query, lower_source, link_project
    ir=link_project([lower_source('def items():\n yield 1\n','python','a.py')])
    result=evaluate_query(ir,'query q { match "gof.iterator"(iterator:$i); emit $i; }')
    assert len(result['matches'])==1


def test_argument_type_filter_uses_value_metadata(tmp_path):
    (tmp_path/'a.py').write_text('def use(value): return value\nuse("hello")\nuse(2)\n')
    result=search(tmp_path,'query q { call(name: "use") as $c { has_argument(position: 0, type_family: string) as $a; } emit $c,$a; }',cache_mb=0)
    assert len(result['matches'])==1


def test_positive_join_planner_avoids_generator_cartesian_product():
    # Real-corpus regression: Werkzeug exhausted 100k states when all operation
    # candidates were combined with each generator before joining ownership.
    ir = IR('large', 'python')
    for i in range(400):
        ir.add(f'f{i}', 'ENTITY', 'CALLABLE', generator=True)
        ir.add(f'o{i}', 'OPERATION', 'yield', kind='yield')
        ir.add(f'f{i}', 'HAS_OPERATION', f'o{i}')
    query = '''query generators {
      callable(generator: true) as $iterator;
      operation(kind: yield) as $suspend;
      require $iterator HAS_OPERATION $suspend;
      emit $iterator;
    }'''
    result = execute(ir, query, budget=QueryBudget(max_states=10000, max_rows=10000, max_matches=1000))
    assert result['complete']
    assert len(result['matches']) == 400
    assert result['stats']['rows_examined'] < 2000


@pytest.mark.parametrize('reverse', [False, True])
def test_join_planner_preserves_repeated_bindings_and_attributes(reverse):
    ir = graph(('a', 'LINK', 'a'), ('a', 'LINK', 'b'), ('b', 'LINK', 'b'))
    ir.add('a', 'ENTITY', 'CALLABLE', name='wanted')
    ir.add('b', 'ENTITY', 'CALLABLE', name='other')
    clauses = ['require $x LINK $x;', 'callable(name: "wanted") as $x;']
    if reverse:
        clauses.reverse()
    result = execute(ir, 'query q {' + ''.join(clauses) + 'emit $x;}')
    assert [hit['bindings'] for hit in result['matches']] == [{'$x': 'a'}]
