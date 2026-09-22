from dataclasses import replace

import pytest

from ken.kql2 import parse
from ken.kql2.compiler import CompileError, compile
from ken.kql2.execution import execute
from ken.structural.frontend import lower_source
from ken.structural.model import Entity, Fact, IR
from ken.structural_store import Store

HEADER = 'language "kql/2"; module test; '


def compiled(text):
    return compile(parse(HEADER + text))


def graph_fixture(store):
    ir = IR('src/abc/a.py','python')
    for i in range(40):
        cid,mid = f'c{i}',f'm{i}'
        ir.entities[cid] = Entity(cid,'CLASS',f'Class{i}',ir.path,1,4)
        ir.entities[mid] = Entity(mid,'CALLABLE','work' if i % 2 else 'build',ir.path,2,3,{'static':False})
        ir.facts.append(Fact(cid,'HAS_METHOD',mid))
    unit = store.put_unit('u',ir,'h','v')
    return store.publish([unit],expected_parent=None)


@pytest.mark.parametrize('query', [
    'query q { class $c { name: "Class3"; method $m { name: "work"; } } select $c,$m; }',
    'query q { class $c { name: /Class[12]$/; method $m {} } where $m.name == "work"; select $c; }',
    'query q { from TypeDecl $a, TypeDecl $b; where $a != $b; select $a,$b; limit 5; }',
    'query q { class $c {} when $c.language in ["python"] { method $m { name: "work"; } } else { method $m { name: "no"; } } select $c; }',
    'query q { class $c { when in_directory($c,"abc") { method $m { name: "work"; } } else { method $m { name: "no"; } } } select $c,$m; }',
    'query q { { class $c { name: "Class1"; } } or { class $c { name: "Class2"; } } select $c; }',
    'query q { class $c {} select $c.name; order by $c.name desc; limit 5; }',
])
def test_differential(query):
    # Standalone method requires an explicit owner in this first capability.
    query = query.replace('class $c {} when', 'class $c { when').replace('} select $c; }', '} } select $c; }') if 'class $c {} when' in query else query
    program = replace(compiled(query), limit=None)
    with Store() as store:
        snapshot = graph_fixture(store)
        indexed = execute(program,store,snapshot)
        reference = execute(program,store,snapshot,reference=True)
        assert set(indexed.rows) == set(reference.rows)
        assert indexed.complete == reference.complete
        assert indexed.unknown_candidates == reference.unknown_candidates
        assert indexed.scanned_nodes <= reference.scanned_nodes


def test_patterns_multiple_independent_invocations():
    program = compiled('''
      pattern Choice(out TypeDecl $c) {
        { class $c { name: "Class1"; } } or { class $c { name: "Class2"; } }
      }
      query q { use Choice(c:$a); use Choice(c:$b); select $a,$b; }
    ''')
    with Store() as store:
        out = execute(program,store,graph_fixture(store))
        assert {(a.name,b.name) for a,b in out.rows} == {('Class1','Class1'),('Class1','Class2'),('Class2','Class1'),('Class2','Class2')}


def test_path_component_and_language_else():
    program = compiled('''query q {
      class $c {
        when $c.language in ["java","c"] { method $m { name: "never"; } }
        else when in_directory($c,"abc") { method $m { name: "work"; } }
        else { method $m { name: "build"; } }
      } select $c,$m;
    }''')
    with Store() as store:
        out = execute(program,store,graph_fixture(store))
        assert len(out.rows) == 20
        assert all(m.name=='work' for c,m in out.rows)
    for path, expected in [('abc/a.py',20),('a/abc/deep/a.py',20),('abcdef/a.py',0),('src/abc',0)]:
        with Store() as store:
            ir=IR(path,'python',entities={'c':Entity('c','CLASS','C',path,1,2)})
            u=store.put_unit('u',ir,'h','v')
            p=compiled('query q { class $c {} where in_directory($c,"abc"); select $c; }')
            assert bool(execute(p,store,store.publish([u],expected_parent=None)).rows) == bool(expected)


def test_unknown_not_false_branch():
    p=compiled('query q { class $c { method $m { when $m.static == true { name: "work"; } else { name: "build"; } } } select $m; }')
    with Store() as store:
        ir=IR('a.py','python')
        ir.entities['c']=Entity('c','CLASS','C',ir.path,1,4)
        ir.entities['m']=Entity('m','CALLABLE','work',ir.path,2,3)
        ir.facts.append(Fact('c','HAS_METHOD','m'))
        uid=store.put_unit('u',ir,'h','v')
        out=execute(p,store,store.publish([uid],expected_parent=None))
        assert out.rows == [] and out.unknown_candidates > 0


@pytest.mark.parametrize('text', [
    'query q { class $c { body { return $x; } } select $c; }',
    'query q { class $c { type: string; } select $c; }',
    'query q { class $c {} select $missing; }',
    'query q { class $c { name: true; } select $c; }',
    'query q { class $c {} where $c.name == 1; select $c; }',
    'query q { { class $a {} } or { class $b {} } select $a; }',
    'pattern P(in TypeDecl $c) { class $c {} } query q { use P(); select 1; }',
])
def test_fail_closed(text):
    with pytest.raises(CompileError):
        compiled(text)


def test_unknown_projection_and_budget():
    with Store() as store:
        snapshot=graph_fixture(store)
        p=compiled('query q { class $c {} select $c.native_kind; }')
        result=execute(p,store,snapshot)
        assert not result.rows and result.unknown_candidates == 40
        p=compiled('query q { class $c {} select $c; }')
        assert execute(p,store,snapshot,max_states=2).reason=='max_states'
        assert execute(p,store,snapshot,timeout_ms=0).reason=='timeout'
        assert execute(p,store,snapshot,cancelled=lambda:True).reason=='cancelled'
        assert execute(p,store,snapshot,max_rows=2).complete is False
        limited=execute(replace(p,limit=2),store,snapshot)
        assert limited.complete and limited.results_truncated and len(limited.rows)==2


@pytest.mark.parametrize('language,source', [
    ('python','class Worker:\n def work(self,task):\n  return task\n'),
    ('java','class Worker { String work(String task) { return task; } }'),
    ('typescript','class Worker { work(task: string) { return task; } }'),
    ('csharp','class Worker { string work(string task) { return task; } }'),
    ('cpp','class Worker { public: int work(int task) { return task; } };'),
])
def test_real_frontend_ownership_and_receiver(language,source):
    with Store() as store:
        ir=lower_source(source,language,'source')
        unit=store.put_unit('u',ir,'h','v')
        snap=store.publish([unit],expected_parent=None)
        p=compiled('query q { class $c { name: "Worker"; method $m { name: "work"; param $p { position: 0; } } } select $p.name; }')
        assert execute(p,store,snap).rows == [('task',)]


def test_selective_query_uses_index():
    with Store() as store:
        snapshot=graph_fixture(store)
        p=compiled('query q { class $c { name: "Class3"; } select $c; }')
        out=execute(p,store,snapshot)
        assert len(out.rows)==1 and out.scanned_nodes==1
        sql,args=store.scan_sql(snapshot,kind='CLASS',name='Class3')
        explain=str(store.db.execute('EXPLAIN QUERY PLAN '+sql,args).fetchall())
        assert 'k2_nodes_kind_name' in explain


def test_branch_guard_prunes_before_child_scans():
    p=compiled('query q { class $c { when $c.language in ["java"] { method $m {} } else { method $m { name: "work"; } } } select $m; }')
    with Store() as store:
        result=execute(p,store,graph_fixture(store))
        assert len(result.rows)==20
        # 40 classes per branch, and only 20 matching methods in the Python arm.
        assert result.scanned_nodes==100


def test_unknown_branch_property_is_not_an_empty_result_certificate():
    p=compiled('query q { class $c { method $m { static: true; } } select $m; }')
    with Store() as store:
        ir=IR('a.py','python')
        ir.entities['c']=Entity('c','CLASS','C',ir.path,1,3)
        ir.entities['m']=Entity('m','CALLABLE','m',ir.path,2,3,{'static':None})
        ir.facts=[Fact('c','HAS_METHOD','m')]
        uid=store.put_unit('u',ir,'h','v')
        out=execute(p,store,store.publish([uid],expected_parent=None))
        assert out.unknown_candidates == 1
        assert not out.rows


def test_unknown_language_does_not_choose_else():
    # Conditions are three-valued even when used to select an implementation.
    p=compiled('query q { class $c { method $m { when $m.native_kind == "known" { name: "work"; } else { name: "build"; } } } select $m; }')
    with Store() as store:
        out=execute(p,store,graph_fixture(store))
        assert not out.rows and out.unknown_candidates == 40


def test_exponential_alternatives_are_rejected():
    text='query q {' + '{ class $c {} } or { class $c {} } '*8 + 'select $c; }'
    with pytest.raises(CompileError,match='expansion limit'):
        compiled(text)


def test_pattern_recursion_fails_before_expansion():
    with pytest.raises(CompileError,match='recursive'):
        compiled('pattern P(out TypeDecl $c) { use P(c:$c); } query q { use P(c:$c); select $c; }')


@pytest.mark.parametrize('duration',[float('nan'),float('inf'),-1])
def test_invalid_timeout(duration):
    with Store() as store:
        with pytest.raises(ValueError):
            execute(compiled('query q { select 1; }'),store,0,timeout_ms=duration)


def test_hygiene_through_nested_named_arguments():
    p=compiled('''
      pattern Inner(out TypeDecl $c, out Callable $m) { class $c { method $m {} } }
      pattern Outer(out TypeDecl $c) { use Inner(c:$c,m:$private); }
      query q { use Outer(c:$a); use Outer(c:$b); where $a != $b; select $a,$b; }
    ''')
    with Store() as store:
        out=execute(p,store,graph_fixture(store))
        assert len(out.rows)==40*39


def test_pattern_can_restrict_an_existing_supertype_binding():
    p=compiled('''
      pattern Choice(in TypeDecl $c) { class $c { name: "Class1"; } }
      query q { from TypeDecl $c; use Choice(c:$c); select $c; }
    ''')
    with Store() as store:
        out=execute(p,store,graph_fixture(store))
        assert len(out.rows)==1 and out.rows[0][0].name=='Class1'
