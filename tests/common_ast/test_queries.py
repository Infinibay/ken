import pytest
from ken.kql2.service import search
from .sources import SOURCES, EXTENSIONS


@pytest.mark.parametrize('language',SOURCES)
def test_identical_query_on_each_language(tmp_path,language):
 (tmp_path/('a.'+EXTENSIONS[language])).write_text(SOURCES[language])
 q='''language "kql/2"; module t; query q {
 statement $n {kind:"return";} select $n.kind,$n.namespace;
 }'''
 result=search(tmp_path,q,cache_mb=0)
 assert result['complete'] and len(result['rows'])==1 and result['rows'][0][0]=='return'
 assert result['rows'][0][1].endswith('.f')


def test_parent_containment_is_syntactic_not_execution(tmp_path):
 (tmp_path/'a.py').write_text('def f():\n return 1\n x=2\n')
 q='''language "kql/2"; module t; query q {
 node $f {kind:"callable"; node $body {kind:"block";} }
 node $dead {kind:"assignment";}
 where contains($body,$dead);
 select $dead.line;
 }'''
 assert search(tmp_path,q,cache_mb=0)['rows']==[[3]]


def test_same_symbol_does_not_unify_shadowed_names(tmp_path):
 (tmp_path/'a.ts').write_text('function f() { let x=1; {let x=2; use(x);} return x; }')
 q='''language "kql/2"; module t; query q {
 node $decl {kind:"binding_declaration"; name:"x";}
 node $use {kind:"identifier";name:"x";}
 where same_symbol($decl,$use);
 select $decl.start_byte,$use.start_byte;
 }'''
 rows=search(tmp_path,q,cache_mb=0)['rows']
 assert len(rows)==2
 assert len({row[0] for row in rows})==2 and len({row[1] for row in rows})==2


def test_visibility_and_initialization_are_distinct_queries(tmp_path):
 (tmp_path/'a.ts').write_text('function f() { use(x); let x=2; return x; }')
 header='''language "kql/2"; module t; query q {
 node $decl {kind:"binding_declaration";name:"x";}
 node $use {kind:"identifier";name:"x";}
 where RELATION($decl,$use); select $use.start_byte; }'''
 visible=search(tmp_path,header.replace('RELATION','visible_at'),cache_mb=0)['rows']
 initialized=search(tmp_path,header.replace('RELATION','initialized_at'),cache_mb=0)['rows']
 assert len(visible)==2 and len(initialized)==1 and initialized[0] in visible


def test_query_result_invalidates_after_scope_edit(tmp_path):
 source=tmp_path/'a.ts'; source.write_text('function f() { let x=1; return x; }')
 q='language "kql/2"; module t; query q {node $n {kind:"return";} select $n.namespace;}'
 assert search(tmp_path,q)['rows']==[['a.ts.f']]
 source.write_text('function renamed() { let x=1; return x; }')
 result=search(tmp_path,q)
 assert result['rows']==[['a.ts.renamed']] and result['analysis']['result_cache']=='miss'


def test_ast_anti_join_is_executable(tmp_path):
 (tmp_path/'a.py').write_text('def f():\n return 1\n')
 q='''language "kql/2"; module t; query q {
 node $n {kind:"return";}
 not exists {node $child {kind:"literal";} where contains($n,$child);}
 select $n.line; }'''
 result=search(tmp_path,q,cache_mb=0)
 assert result['complete'] and result['rows']==[] and result['unknown_candidates']==0


def test_indexed_query_matches_full_scan_and_counts_candidates(tmp_path):
 (tmp_path/'a.py').write_text('def f():\n x=1\n y=x+2\n return y\n')
 q='language "kql/2"; module t; query q {node $n {kind:"return";} select $n.line;}'
 indexed=search(tmp_path,q,cache_mb=0)
 reference=search(tmp_path,q,cache_mb=0,reference=True)
 assert indexed['rows']==reference['rows']==[[4]]
 assert indexed['analysis']['scanned_nodes']==1
 assert reference['analysis']['scanned_nodes']>10


def test_uncertain_argument_position_is_not_a_false_negative(tmp_path):
 (tmp_path/'a.ts').write_text('f(...xs, y);')
 q='''language "kql/2"; module t; query q {
 node $n {name:"y"; argument_position:1;} select $n.line; }'''
 result=search(tmp_path,q,cache_mb=0)
 assert result['rows']==[] and result['unknown_candidates']==1


def test_common_ast_cannot_nest_under_legacy_owner(tmp_path):
 from ken.kql2.compiler import CompileError
 q='language "kql/2"; module t; query q {module_decl $m {node $n {}} select $n;}'
 with pytest.raises(CompileError): search(tmp_path,q)
 assert not (tmp_path/'.ken').exists()


def test_opaque_syntax_does_not_certify_absence(tmp_path):
 (tmp_path/'a.py').write_text('def f(x):\n match x:\n  case [a,b]: return a\n')
 q='''language "kql/2"; module t; query q {
 not exists {node $n {kind:"yield";}}
 select 1; }'''
 result=search(tmp_path,q,cache_mb=0)
 assert result['complete'] and result['rows']==[] and result['unknown_candidates']>0
