"""Template Method: instance-correlated extension calls and dependent steps."""
import re

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


LANGUAGES = ['python','java','typescript']
DEPENDENT_STEPS = '''query template_dependent_steps {
 match "template-method"(unit:$unit);
 require $unit INSTANCE_RECEIVER $self;
 require $unit HAS_METHOD $template;
 require $unit HAS_METHOD $first_slot;
 require $unit HAS_METHOD $second_slot;
 require $override OVERRIDES $first_slot;
 require $template HAS_CALL $first;
 require $template HAS_CALL $second;
 require $first TARGET $first_slot;
 require $second TARGET $second_slot;
 require $first RECEIVER $self;
 require $second RECEIVER $self;
 require $first RESULT $value;
 require $second ARGUMENT $argument;
 require $argument VALUE $value;
 different $first_slot $second_slot;
 different $template $first_slot;
 different $template $second_slot;
 emit $unit,$template,$first,$second;
}'''


def source(language, noise=False):
    if language == 'python':
        steps = '  self.before()\n  return self.second(self.first(key))\n'
        if noise:
            steps = steps.replace('  return ', '  metric=1+2\n  print(metric)\n  return ')
        return '''class Base:
 def first(self,key): pass
 def second(self,value): return value+1
 def before(self): pass
 def run(self,key,other:Base):
'''+steps+'''class Concrete(Base):
 def first(self,key): return key*2
'''
    steps = 'this.before(); return this.second(this.first(key));'
    if noise:
        log = 'int metric=1+2; System.out.println(metric);' if language == 'java' else 'const metric=1+2; console.log(metric);'
        steps = steps.replace('return ', log+' return ')
    if language == 'java':
        return '''abstract class Base {
 abstract int first(int key);
 int second(int value){return value+1;}
 void before(){}
 int run(int key,Base other){'''+steps+'''}
}
class Concrete extends Base {int first(int key){return key*2;}}
'''
    return '''abstract class Base {
 abstract first(key:number):number;
 second(value:number):number{return value+1;}
 before():void{}
 run(key:number,other:Base):number{'''+steps+'''}
}
class Concrete extends Base {first(key:number):number{return key*2;}}
'''


def detect(text, language, refined=True):
    graph = link_project([lower_source(text, language, 'template.'+{'python':'py','java':'java','typescript':'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('template-dependent-steps', DEPENDENT_STEPS) if refined else named_rule('template-method', registry)
    result = execute_rules(graph, [rule], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['baseline','noise','renamed'])
def test_same_instance_dependent_steps_survive_noise_and_optional_default_hook(language, mode):
    text = source(language, mode != 'baseline')
    if mode == 'renamed':
        for old,new in [('Base','Recipe'),('Concrete','Specialized'),('first','prepare'),('second','complete')]:
            text=re.sub(r'\b'+old+r'\b',new,text)
    assert detect(text, language)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['other-instance','discard-first-result'])
def test_refinement_rejects_broken_instance_or_data_collaboration(language, mutation):
    text = source(language, True)
    receiver = 'self' if language == 'python' else 'this'
    if mutation == 'other-instance':
        text = text.replace(f'{receiver}.first(key)', 'other.first(key)')
    else:
        text = text.replace(f'{receiver}.second({receiver}.first(key))', f'{receiver}.second(0)')
        text = text.replace('  return ', '  self.first(key)\n  return ') if language == 'python' else text.replace('return this.second', 'this.first(key);return this.second')
    assert detect(text, language, refined=False)
    assert not detect(text, language)


@pytest.mark.parametrize('language', LANGUAGES)
def test_two_concrete_steps_without_extension_override_are_not_nominal_template(language):
    text = source(language, True)
    text = text[:text.index('class Concrete')]
    assert not detect(text, language, refined=False)


@pytest.mark.parametrize('language', LANGUAGES)
def test_reversed_independent_calls_do_not_satisfy_dependent_step_contract(language):
    text = source(language, True)
    receiver = 'self' if language == 'python' else 'this'
    replacement = f'{receiver}.second(0)\n  return {receiver}.first(key)' if language == 'python' else f'{receiver}.second(0);return {receiver}.first(key)'
    text = text.replace(f'return {receiver}.second({receiver}.first(key))', replacement)
    assert detect(text, language, refined=False)
    assert not detect(text, language)
