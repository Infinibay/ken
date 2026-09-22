"""External function slots require qualified Java API identity, not method names."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

@pytest.mark.parametrize('spelling,imports,tail,expected',[
 ('IntSupplier','import java.util.function.IntSupplier;','',True),
 ('java.util.function.IntSupplier','','',True),
 ('IntSupplier','','',False),
 ('IntSupplier','import other.IntSupplier;','',False),
 ('IntSupplier','import java.util.function.*;','',False),
 ('IntSupplier','import java.util.function.IntSupplier; import other.IntSupplier;','',False),
 ('IntSupplier','import java.util.function.IntSupplier;','interface IntSupplier { int getAsInt(); }',False),
])
def test_supplier_slot_requires_unambiguous_nominal_identity(spelling,imports,tail,expected):
 source=imports+'class Use { int work('+spelling+' source){return source.getAsInt();} }'+tail
 graph=link_project([lower_source(source,'java','Use.java')])
 modeled=[f for f in graph.facts if f.relation=='DECLARED_TARGET' and f.attrs.get('model')=='java-functional-slots/1']
 assert bool(modeled) is expected
 if expected:
  target=graph.entities[modeled[0].object]
  assert target.attrs['external'] and target.attrs['arity']==0
  assert not [f for f in graph.facts if f.subject==modeled[0].subject and f.relation=='TARGET']


def test_type_parameter_shadows_imported_function_interface():
 source='import java.util.function.IntSupplier; class Use<IntSupplier> { int work(IntSupplier source){return source.getAsInt();} }'
 graph=link_project([lower_source(source,'java','Use.java')])
 assert not [f for f in graph.facts if f.attrs.get('model')=='java-functional-slots/1']

@pytest.mark.parametrize('call,expected',[('applyAsInt(1)',True),('applyAsInt()',False),('applyAsInt(1,2)',False),('other(1)',False)])
def test_unary_operator_models_only_its_declared_slot_and_arity(call,expected):
 source='import java.util.function.IntUnaryOperator; class Use {int work(IntUnaryOperator op){return op.'+call+';}}'
 graph=link_project([lower_source(source,'java','Use.java')])
 modeled=[f for f in graph.facts if f.relation=='DECLARED_TARGET' and f.attrs.get('model')=='java-functional-slots/1']
 assert bool(modeled) is expected
 if expected:
  parameters=[f for f in graph.facts if f.subject==modeled[0].object and f.relation=='HAS_PARAMETER']
  assert len(parameters)==1 and parameters[0].attrs['position']==0
