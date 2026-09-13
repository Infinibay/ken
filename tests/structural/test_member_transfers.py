"""Bounded last member input excludes unsupported control and reassigned inputs."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


@pytest.mark.parametrize('body,expected,status',[
 ('self.part.value=value',True,'supported'),
 ('self.part.value=value\nreturn self',True,'supported'),
 ('self.part.value=value\nreturn self\nself.part.value=0',True,'supported'),
 ('self.part.value=0\nself.part.value=value',True,'supported'),
 ('self.part.value=value\nself.part.value=0',False,'supported'),
 ('value=0\nself.part.value=value',False,'supported'),
 ('self.part.value=value\nvalue=0',False,'supported'),
 ('self.part.value=value\nself.other=value',True,'supported'),
 ('return self\nself.part.value=value',False,'supported'),
 ('self.part.value+=value',False,'unsupported'),
 ('self.part.value=value\nif flag: self.part.value=0',False,'unsupported'),
 ('for x in xs: self.part.value=value',False,'unsupported'),
 ('while flag: self.part.value=value',False,'unsupported'),
 ('try: self.part.value=value\nexcept Error: pass',False,'unsupported'),
 ('self.part.value=value\nraise Error()',False,'unsupported'),
 ('self.part.value=value\nyield self',False,'unsupported'),
 ('self.part.value=value\nexec(code)',False,'unsupported'),
 ('self.part.value=value\nlocals()',False,'unsupported'),
 ('self.part.value=value\ndef inner(): pass',False,'unsupported'),
 ('self.part.value=value\ndel self.part',False,'unsupported'),
])
def test_last_member_input_contract(body,expected,status):
    source='class C:\n def set(self,value):\n'+''.join('  '+line+'\n' for line in body.splitlines())
    graph=link_project([lower_source(source,'python','member.py')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    states=[f for f in graph.facts if f.relation=='MEMBER_FLOW_STATUS']
    assert len(states)==1 and states[0].object==status,states
    query='''query q {
      require $write FINAL_MEMBER_INPUT $input [basis: linear-syntax];
      require $write ASSIGNMENT_TARGET $member;
      emit $write,$input,$member;
    }'''
    out=execute_rules(graph,[SavedRule('member',query)])
    assert out['complete'] and bool(out['matches'])==expected,out
    operations={o.id:o for o in graph.operations}
    for match in out['matches']:
        assert match['bindings']['$write'] in operations
        assert graph.entities[match['bindings']['$input']].kind=='PARAMETER'
