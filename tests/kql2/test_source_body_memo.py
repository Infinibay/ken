"""Outer joins must not repeatedly execute an unchanged body predicate."""
from ken.kql2.body import BodyEngine
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget


def test_irrelevant_outer_roles_do_not_repeat_body_work_or_lose_matches(monkeypatch):
    source='\n'.join(f'class C{i}:\n pass' for i in range(30))+'\ndef work():\n return 1\n'
    query='''language "kql/2"; module memo;
    pattern detect(out TypeDecl $other, out Callable $owner) {
      class $other {}
      callable $owner { name: "work"; body { return 1; } }
    }
    query results { use detect(other: $other, owner: $owner); select $other,$owner; }'''
    calls=[]
    original=BodyEngine.match
    def match(self,pattern,bindings,**kwargs):
        calls.append(pattern.owner)
        yield from original(self,pattern,bindings,**kwargs)
    monkeypatch.setattr(BodyEngine,'match',match)
    index=query_graph(link_project([lower_source(source,'python','memo.py')]))
    result=Executor(index,{},QueryBudget()).execute(compile_source(query))
    assert result['complete'] and len(result['matches']) == 30,result
    assert len(calls) == 1


def test_body_memo_keeps_receiver_and_argument_constraints_distinct(monkeypatch):
    contexts = []
    original = BodyEngine.match_context
    def context(self, owner, region):
        contexts.append((owner.local_id, region))
        return original(self, owner, region)
    monkeypatch.setattr(BodyEngine, 'match_context', context)
    source='''def consume(value): pass
class C:
 def work(self, first, second):
  consume(first)
'''
    query='''language "kql/2"; module memo;
    pattern detect(out Parameter $input) {
      callable $consume { name: "consume"; }
      callable $owner { name: "work"; param $input {}
        body { call $consume { argument $input at 0; }; }
      }
    }
    query results { use detect(input: $input); select $input; }'''
    index=query_graph(link_project([lower_source(source,'python','memo.py')]))
    result=Executor(index,{},QueryBudget()).execute(compile_source(query))
    assert result['complete'] and len(result['matches']) == 1,result
    assert '/PARAMETER:first' in result['matches'][0]['bindings']['$input']
    assert len(contexts) == 1


def test_equal_body_plans_share_cached_hash_without_changing_structural_identity():
    from dataclasses import replace
    from ken.kql2.source_execution import _PatternKey

    plan = compile_source('''language "kql/2"; module hash_memo;
      query q { callable $owner { body { return 1; } } select $owner; }
    ''')
    pattern = next(node.value for node in plan.nodes if node.kind == 'source_body')
    equal = replace(pattern)
    first, second = _PatternKey(pattern), _PatternKey(equal)
    assert first == second and hash(first) == hash(second) == hash(pattern)
    assert {first: "cached"}[second] == "cached"
    changed = _PatternKey(replace(pattern, owner="other"))
    assert first != changed
