"""A replaceable algorithm does not require two implementations in the scan."""
import pytest
from ken.structural.rules import builtin_rules, named_rule, execute_rules
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

SOURCES={
 'python':'''class Contract:
 def apply(self,x): return x
class Single(Contract):
 def apply(self,x): return x*2
class Context:
 policy:Contract
 def configure(self,policy:Contract): self.policy=policy
 def run(self,x): return self.policy.apply(x)
''',
 'java':'''interface Contract { int apply(int x); }
 class Single implements Contract {public int apply(int x){return x*2;}}
 class Context {Contract policy; void configure(Contract p){this.policy=p;} int run(int x){return this.policy.apply(x);} }''',
 'typescript':'''interface Contract {apply(x:number):number;}
 class Single implements Contract {apply(x:number){return x*2;}}
 class Context {policy:Contract; configure(p:Contract){this.policy=p;} run(x:number){return this.policy.apply(x);} }''',
}
@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','unused_policy'])
def test_replaceable_contract_needs_use_not_implementation_count(language,mutation):
 source=SOURCES[language]
 if mutation=='unused_policy':source=source.replace('return self.policy.apply(x)','return x').replace('return this.policy.apply(x)','return x')
 graph=link_project([lower_source(source,language,'sample.'+language)])
 registry=builtin_rules()
 rule=named_rule('strategy#strategy-object',registry)
 result=execute_rules(graph,[rule],registry=registry)
 assert result['complete'],result
 assert bool(result['matches']) is (mutation=='positive'),result

from .test_algorithm_strategy import source as consumed_source, CASES

@pytest.mark.parametrize('language,kind',CASES)
@pytest.mark.parametrize('mutation',['positive','wrong-input','discard-result','overwrite-result','rebound-input'])
def test_consumed_policy_requires_original_input_and_returned_invocation(language,kind,mutation):
 source=consumed_source(language,kind,'' if mutation=='positive' else mutation)
 graph=link_project([lower_source(source,language,'sample.'+language)])
 registry=builtin_rules()
 rule=named_rule('strategy.consumed_policy',registry)
 result=execute_rules(graph,[rule],registry=registry)
 assert result['complete'],result
 assert bool(result['matches']) is (mutation=='positive'),result
