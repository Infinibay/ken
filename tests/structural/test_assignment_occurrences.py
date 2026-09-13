"""Syntax operands retain occurrence identity before reaching-definition analysis."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.kenql import Engine, parse
from ken.structural.model import IR, FactIndex

SOURCES = {
 'python': 'def f():\n x = first()\n x = second()\n return x\n',
 'javascript': 'function f(){let x=first();x=second();return x;}',
 'typescript': 'function f(){let x=first();x=second();return x;}',
 'java': 'class C { Object f(){Object x=first();x=second();return x;} }',
 'csharp': 'class C { object F(){object x=First();x=Second();return x;} }',
 'cpp': 'int f(){int x=first();x=second();return x;}',
 'rust': 'fn f()->i32 {let mut x=first();x=second();return x;}',
 'go': 'package p; func f()int{x:=first();x=second();return x}',
}

@pytest.mark.parametrize('language', SOURCES)
def test_successive_writes_and_return_remain_correlated(language):
 g=link_project([lower_source(SOURCES[language],language,'sample')])
 assert not g.diagnostics
 writes={f.subject:f.object for f in g.facts if f.relation=='ASSIGNMENT_TARGET'}
 values={f.subject:f.object for f in g.facts if f.relation=='ASSIGNMENT_VALUE'}
 returns=[f for f in g.facts if f.relation=='RETURN_OPERAND']
 assert len(writes)==2 and len(set(writes.values()))==1
 assert writes.keys()==values.keys() and len(set(values.values()))==2
 assert len(returns)==1 and returns[0].object in writes.values()
 operations={o.id:o for o in g.operations}
 ordered=sorted(writes,key=lambda key:operations[key].start)
 assert operations[ordered[0]].start<operations[ordered[1]].start<operations[returns[0].subject].start
 assert len({operations[k].owner for k in [*writes,returns[0].subject]})==1
 # Both source serialization and public graph queries preserve the pairing.
 restored=IR.from_dict(g.to_dict())
 result=Engine(FactIndex(restored),{}).execute(parse('query q { require $w ASSIGNMENT_TARGET $s; require $w ASSIGNMENT_VALUE $v; emit $w,$s,$v; }'))
 assert result['complete'] and len(result['matches'])==2

def test_empty_graph_accepts_registered_operand_relations():
 result=Engine(FactIndex(IR('empty','python')),{}).execute(parse('query q { require $r RETURN_OPERAND $v; emit $r,$v; }'))
 assert result['matches']==[]

def test_nested_return_keeps_execution_owner():
 g=lower_source('def f():\n x=1\n def inner():\n  return x\n return inner\n','python','sample')
 ops={o.id:o for o in g.operations}
 owners={g.entities[ops[f.subject].owner].name for f in g.facts if f.relation=='RETURN_OPERAND'}
 assert owners=={'f','inner'}

def test_bare_return_has_no_operand():
 g=lower_source('def f():\n return\n','python','sample')
 assert not any(f.relation=='RETURN_OPERAND' for f in g.facts)

def test_compound_assignment_retains_operator_and_rhs_operand():
 g=lower_source('function f(){let x=1;x+=2;return x;}','javascript','sample')
 ops={o.id:o for o in g.operations}
 compound=[f for f in g.facts if f.relation=='ASSIGNMENT_VALUE' and '+=' in ops[f.subject].attrs['tokens']]
 assert len(compound)==1
 assert g.entities[compound[0].object].attrs['native_kind']=='number'
