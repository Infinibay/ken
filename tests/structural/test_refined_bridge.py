"""Refined abstractions delegate through a separate implementation hierarchy."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules

LANGUAGES=['python','typescript','java','csharp']
CASES=['positive','renamed','field-form','extra-implementation','no-override',
       'no-base','one-implementation','unrelated-contract','unused-field',
       'wrong-receiver','same-hierarchy']
POSITIVE={'positive','renamed','field-form','extra-implementation'}


def source(language,case='positive',inherited=False):
    if language=='python':
        text='''class Driver:
 def run(self): pass
class First(Driver):
 def run(self): return 1
class Second(Driver):
 def run(self): return 2
class Other: pass
class Base:
 def render(self): pass
class Subject(Base):
 def __init__(self,driver:Driver):
  self.driver:Driver=driver
 def render(self): return self.driver.run()
'''
        if inherited:
            text=text.replace('class Base:\n def render(self): pass\nclass Subject(Base):\n', 'class Base:\n')
            text=text.replace(' def render(self): return self.driver.run()', ' def render(self): pass\nclass Subject(Base):\n def render(self): return self.driver.run()')
        replacements={'field-form':('self.driver:Driver=','self.driver='),
          'no-override':('def render(self): return','def helper(self): return'),
          'no-base':('class Subject(Base):','class Subject:'),
          'one-implementation':('class Second(Driver):','class Second:'),
          'unrelated-contract':('driver:Driver','driver:Other'),
          'unused-field':('return self.driver.run()','return 1'),
          'wrong-receiver':('return self.driver.run()','return other.run()'),
          'same-hierarchy':('class Subject(Base):','class Subject(Driver):')}
        if case=='extra-implementation':text+='class Third(Driver):\n def run(self): return 3\n'
    elif language=='typescript':
        text='''interface Driver {run():number;}
class First implements Driver {run(){return 1;}}
class Second implements Driver {run(){return 2;}}
class Other {}
class Base {render(){return 0;}}
class Subject extends Base {
 driver:Driver;
 constructor(driver:Driver){super();this.driver=driver;}
 render(){return this.driver.run();}
}
'''
        if inherited:
            text=text.replace('class Base {render(){return 0;}}\nclass Subject extends Base {','class Base {').replace('super();','')
            text=text.replace(' render(){return this.driver.run();}', ' render(){return 0;}\n}\nclass Subject extends Base {\n render(){return this.driver.run();}')
        replacements={'field-form':(' driver:Driver;',''),
          'no-override':('render(){return this','helper(){return this'),
          'no-base':('Subject extends Base','Subject'),
          'one-implementation':('Second implements Driver','Second'),
          'unrelated-contract':('driver:Driver','driver:Other'),
          'unused-field':('return this.driver.run()','return 1'),
          'wrong-receiver':('return this.driver.run()','return other.run()'),
          'same-hierarchy':('Subject extends Base','Subject implements Driver')}
        if case=='extra-implementation':text+='class Third implements Driver {run(){return 3;}}'
    else:
        cs=language=='csharp';extends=':' if cs else 'extends';implements=':' if cs else 'implements'
        text=f'''interface Driver {{int run();}}
class First {implements} Driver {{public int run(){{return 1;}}}}
class Second {implements} Driver {{public int run(){{return 2;}}}}
class Other {{}}
class Base {{public {'virtual ' if cs else ''}int render(){{return 0;}}}}
class Subject {extends} Base {{
 Driver driver;
 public Subject(Driver driver){{this.driver=driver;}}
 public {'override ' if cs else ''}int render(){{return this.driver.run();}}
}}
'''
        replacements={'field-form':(' Driver driver;',' private Driver driver;'),
          'no-override':('int render(){return this','int helper(){return this'),
          'no-base':(f'Subject {extends} Base','Subject'),
          'one-implementation':(f'Second {implements} Driver','Second'),
          'unrelated-contract':('Driver driver','Other driver'),
          'unused-field':('return this.driver.run()','return 1'),
          'wrong-receiver':('return this.driver.run()','return other.run()'),
          'same-hierarchy':(f'Subject {extends} Base',f'Subject {implements} Driver')}
        if case=='extra-implementation':text+=f'class Third {implements} Driver {{public int run(){{return 3;}}}}'
    if language=='python':text+='class Peer(Base):\n def render(self): pass\n'
    elif language=='typescript':text+='class Peer extends Base {render(){return 0;}}'
    else:text+=f'class Peer {extends} Base {{}}'
    if case in replacements:
        a,b=replacements[case];assert a in text;text=text.replace(a,b)
    if case=='same-hierarchy':text=text.replace('render','run')
    if case=='renamed':
        for a,b in [('Driver','Engine'),('driver','backend'),('Base','View'),('Subject','Panel'),('render','draw'),('run','perform')]:text=text.replace(a,b)
    return text


def detect(text,language):
    graph=link_project([lower_source(text,language,'bridge')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict());rules=builtin_rules()
    result=execute_rules(graph,[named_rule('bridge#refined-composition',rules)],registry=rules)
    assert result['complete'] and all(m['status']=='structural_match' for m in result['matches']),result
    return graph,result


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_refined_local_field(language,case):
    _,result=detect(source(language,case),language)
    assert bool(result['matches'])==(case in POSITIVE),result


@pytest.mark.parametrize('language',['python','typescript'])
@pytest.mark.parametrize('case',CASES)
def test_refined_inherited_field(language,case):
    _,result=detect(source(language,case,inherited=True),language)
    assert bool(result['matches'])==(case in POSITIVE),result


@pytest.mark.parametrize('language',LANGUAGES)
def test_shared_class_field_is_not_instance_composition(language):
    text=source(language)
    if language=='python':
        text=text.replace('class Subject(Base):','class Subject(Base):\n driver:Driver=Driver()').replace('  self.driver:Driver=driver','  pass')
    elif language=='typescript':
        text=text.replace(' driver:Driver;',' static driver:Driver;').replace('this.driver=driver;','').replace('this.driver.run()','Subject.driver.run()')
    else:
        text=text.replace(' Driver driver;',' static Driver driver;').replace('this.driver=driver;','').replace('this.driver.run()','Subject.driver.run()')
    assert not detect(text,language)[1]['matches']


@pytest.mark.parametrize('language',['python','typescript'])
def test_unknown_ancestry_does_not_guess_inherited_slot(language):
    text=source(language,inherited=True)
    text=text.replace('class Base:', 'class Base(Unknown):').replace('class Base {','class Base extends Unknown {')
    assert not detect(text,language)[1]['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_canonical_and_named_variant_expose_consistent_units(language):
    graph,variant=detect(source(language),language);rules=builtin_rules()
    canonical=execute_rules(graph,[named_rule('bridge',rules)],registry=rules)
    assert canonical['complete']
    assert {m['bindings']['$unit'] for m in canonical['matches']}=={m['bindings']['$unit'] for m in variant['matches']}
    assert len(canonical['matches'])==1


@pytest.mark.parametrize('language',LANGUAGES)
def test_single_implementation_of_abstraction_is_not_two_observed_variants(language):
    text=source(language)
    text=text[:text.index('class Peer')]
    assert not detect(text,language)[1]['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_decorator_family_cannot_pose_as_independent_bridge(language):
    text=source(language)
    if language=='python':text=text.replace('class Base:', 'class Base(Driver):')
    elif language=='typescript':text=text.replace('class Base {','class Base implements Driver {run(){return 0;}')
    elif language=='java':text=text.replace('class Base {','class Base implements Driver {public int run(){return 0;}')
    else:text=text.replace('class Base {','class Base : Driver {public int run(){return 0;}')
    assert not detect(text,language)[1]['matches']
