"""Explicit per-callable inventories keep assignment occurrences and local scope."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR


@pytest.mark.parametrize('body,stable,unique,status',[
 ('result=source.load(key)\nreturn result',True,1,'supported'),
 ('result=source.load(key)\nresult=other\nreturn result',True,0,'supported'),
 ('key=other\nresult=source.load(key)\nreturn result',False,1,'supported'),
 ('result=source.load(key)\nkey=other\nreturn result',False,1,'supported'),
 ('if flag:\n result=source.load(key)\nelse:\n result=source.load(key)\nreturn result',True,0,'supported'),
 ('result=source.load(key)\nkey,other=other,key\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\nkey+=1\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\nexec(code)\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\nlocals()\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\ndef inner(): return key\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\nfor item in items: pass\nreturn result',False,0,'unsupported'),
 ('result=source.load(key)\nyield result',False,0,'unsupported'),
 ('result=source.load(key)\ndel key\nreturn result',False,0,'unsupported'),
])
def test_inventory_not_historical_value_flow(body,stable,unique,status):
    source='def fetch(source,key,other,flag):\n'+''.join(' '+line+'\n' for line in body.splitlines())
    graph=link_project([lower_source(source,'python','binding')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    owner=next(e.id for e in graph.entities.values() if e.kind=='CALLABLE' and e.name=='fetch')
    key=next(e.id for e in graph.entities.values() if e.kind=='PARAMETER' and e.name=='key')
    result=next(e.id for e in graph.entities.values() if e.kind=='STORAGE' and e.name=='result')
    states=[f for f in graph.facts if f.relation=='BINDING_WRITE_STATUS' and f.subject==owner]
    assert len(states)==1 and states[0].object==status,states
    assert any(f.subject==owner and f.relation=='UNREASSIGNED_BINDING' and f.object==key for f in graph.facts)==stable
    assert len([f for f in graph.facts if f.relation=='UNIQUE_BINDING_WRITE' and f.object==result])==unique


def test_methods_writing_same_field_keep_separate_operation_scope():
    source='class A:\n def one(self,value): self.field=value\n def two(self,value): self.field=value\n def read(self): return self.field\n'
    graph=link_project([lower_source(source,'python','methods')]);assert not graph.diagnostics
    writes=[f for f in graph.facts if f.relation=='UNIQUE_BINDING_WRITE'];assert len(writes)==2
    assert len({f.subject for f in writes})==2 and len({f.object for f in writes})==1
    ops={o.id:o for o in graph.operations};assert len({ops[f.subject].owner for f in writes})==2
    reader=next(e.id for e in graph.entities.values() if e.name=='read')
    assert any(f.subject==reader and f.relation=='UNREASSIGNED_BINDING' and f.object==writes[0].object for f in graph.facts)
