"""Decorator authoring preserves executable responsibility and delegated result."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,execute_rules,named_rule
from .test_algorithm_decorator import source,body

@pytest.mark.parametrize('language',['python','java','typescript'])
@pytest.mark.parametrize('target',['decorator#typed-delegator','decorator.result_forwarding'])
@pytest.mark.parametrize('mutation',['positive','after','transparent','dead_extra','wrong_receiver','discard_result'])
def test_decorator_source_body_collaboration(language,target,mutation):
 algorithm=body(language)
 if language=='python':
  if mutation=='after':algorithm=algorithm.replace('print("trace")\n','').replace('return result','print("trace")\nreturn result')
  if mutation=='transparent':algorithm=algorithm.replace('print("trace")\n','')
  if mutation=='dead_extra':algorithm=algorithm.replace('print("trace")\n','').replace('return result','return result\nprint("trace")')
  if mutation=='wrong_receiver':algorithm=algorithm.replace('self.inner.run(value)','Contract().run(value)')
  if mutation=='discard_result':algorithm=algorithm.replace('return result','return 0')
 else:
  trace='System.out.println("trace");' if language=='java' else 'console.log("trace");'
  if mutation=='after':algorithm=algorithm.replace(trace,'').replace('return result;',trace+'return result;')
  if mutation=='transparent':algorithm=algorithm.replace(trace,'')
  if mutation=='dead_extra':algorithm=algorithm.replace(trace,'').replace('return result;','return result;'+trace)
  if mutation=='wrong_receiver':algorithm=algorithm.replace('this.inner.run(value)','other.run(value)')
  if mutation=='discard_result':algorithm=algorithm.replace('return result;','return 0;')
 text=source(language,algorithm)
 graph=link_project([lower_source(text,language,'wrapper.'+language)])
 registry=builtin_rules();result=execute_rules(graph,[named_rule(target,registry)],registry=registry)
 assert result['complete'],result
 expected=mutation in ('positive','after') or mutation=='discard_result' and target.endswith('typed-delegator')
 assert bool(result['matches']) is expected,result

from .test_algorithm_bridge import body as bridge_body,statements as bridge_statements

@pytest.mark.parametrize('language',['python','java','typescript'])
@pytest.mark.parametrize('mutation',['positive','saved','discard','overwritten'])
def test_bridge_returned_primitive_source_contract(language,mutation):
 text=bridge_body(language,bridge_statements(language,mutation))
 graph=link_project([lower_source(text,language,'bridge.'+language)])
 registry=builtin_rules();result=execute_rules(graph,[named_rule('bridge.returned_primitive',registry)],registry=registry)
 assert result['complete'],result
 assert bool(result['matches']) is (mutation in ('positive','saved')),result

@pytest.mark.parametrize('language',['python','java','typescript'])
@pytest.mark.parametrize('mutation',['left','right','unrelated','overwritten'])
def test_decorator_object_binary_uses_actual_delegated_value(language,mutation):
 algorithm=body(language)
 trace='print("trace")\n' if language=='python' else 'System.out.println("trace");' if language=='java' else 'console.log("trace");'
 algorithm=algorithm.replace(trace,'')
 expression={'left':'result + 2','right':'2 + result','unrelated':'2 + 3','overwritten':'result + 2'}[mutation]
 algorithm=algorithm.replace('return result','return '+expression)
 if mutation=='overwritten':algorithm=algorithm.replace('return ',('result = 0\n' if language=='python' else 'result = 0;')+'return ')
 graph=link_project([lower_source(source(language,algorithm),language,'wrapper.'+language)])
 registry=builtin_rules();result=execute_rules(graph,[named_rule('decorator#object-wrapper',registry)],registry=registry)
 assert result['complete'],result
 assert bool(result['matches']) is (mutation in ('left','right')),result
