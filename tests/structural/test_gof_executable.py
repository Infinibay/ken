from __future__ import annotations
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules
from .gof_sources import PYTHON, JAVA, TYPESCRIPT

SOURCES = {'python': PYTHON, 'java': JAVA, 'typescript': TYPESCRIPT}


def evaluate(source, language, name):
    unit = lower_source(source, language, 'sample.' + {'python':'py','java':'java','typescript':'ts','csharp':'cs','cpp':'cpp','javascript':'js','go':'go','rust':'rs'}[language])
    assert not unit.diagnostics, unit.diagnostics
    registry = builtin_rules()
    result = execute_rules(link_project([unit]), [named_rule('gof.'+name, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
@pytest.mark.parametrize('name', sorted(PYTHON))
@pytest.mark.parametrize('rename', [False, True])
def test_canonical_pattern_from_source(language, name, rename):
    source = SOURCES[language][name]
    if rename:
        identifiers = re.findall(r'\b(?:class|interface)\s+(\w+)', source)
        substitutions = {identifier:f'Type{i}' for i,identifier in enumerate(dict.fromkeys(identifiers))}
        source = re.sub(r'\b\w+\b', lambda m: substitutions.get(m[0], m[0]), source)
    assert evaluate(source, language, name), (language,name)


@pytest.mark.parametrize('language', sorted(SOURCES))
@pytest.mark.parametrize('name', sorted(PYTHON))
def test_pattern_names_alone_never_match(language, name):
    spelling = name.title().replace('-','')
    source = f'class {spelling}:\n pass\n' if language=='python' else f'class {spelling} {{}}'
    assert not evaluate(source, language, name)

# Remove a defining behavior while preserving the surrounding collaboration.
# These are source mutations, not tests of fabricated pattern facts.
MUTATIONS = {
 'python': {
  'abstract-factory':('return Two()', 'return One()'),
  'adapter':('self.service.run()', '0'),
  'bridge':('self.driver.run()', '0'),
  'builder':('Product(self.x)', 'Product(123)'),
  'chain-of-responsibility':('if request: return self.following.run()', 'return self.following.run()'),
  'command':('command.execute()', 'pass'),
  'composite':('child.run()', 'pass'),
  'decorator':('print("before")', 'pass'),
  'facade':('self.two.run()', 'pass'),
  'factory-method':('return Product()', 'return None'),
  'flyweight':('Product(key)', 'Product(0)'),
  'interpreter':('self.child.evaluate(context)', 'self.child.evaluate(0)'),
  'iterator':('def __iter__(self): return self', 'def __iter__(self): return None'),
  'mediator':('self.two.act()', 'pass'),
  'memento':('self.state = snapshot.state', 'self.state = 0'),
  'observer':('self.listeners.append(listener)', 'pass'),
  'prototype':('Subject(self.state)', 'Subject(0)'),
  'proxy':('if allowed: return self.inner.run()', 'return self.inner.run()'),
  'singleton':('if cls.value is None:', 'if True:'),
  'state':('self.state = Concrete()', 'self.state = None'),
  'strategy':('self.strategy = strategy', 'self.strategy = First()'),
  'template-method':('self.step()', 'pass'),
  'visitor':('visitor.visit(self)', 'visitor.visit(None)'),
 },
 'java': {
  'abstract-factory':('return new Two()', 'return null'),
  'adapter':('return this.service.perform()', 'return 0'),
  'bridge':('return this.driver.run()', 'return 0'),
  'builder':('new Product(this.value)', 'new Product(123)'),
  'chain-of-responsibility':('if(request)', 'if(true)'),
  'command':('command.execute();', ''),
  'composite':('child.run();', ''),
  'decorator':('System.out.println("before");', ''),
  'facade':('this.two.run();', ''),
  'factory-method':('return new Product()', 'return null'),
  'flyweight':('new Product(key)', 'new Product(0)'),
  'interpreter':('this.child.evaluate(context)', 'this.child.evaluate(0)'),
  'iterator':('this.index=this.index+1;', ''),
  'mediator':('this.two.act();', ''),
  'memento':('this.value=snapshot.value', 'this.value=0'),
  'observer':('this.listeners.add(listener);', ''),
  'prototype':('new Subject(this.value)', 'new Subject(0)'),
  'proxy':('if(allowed){return this.inner.run(allowed);}return 0;', 'return this.inner.run(allowed);'),
  'singleton':('if(Subject.instance==null)', 'if(true)'),
  'state':('this.state=new Concrete()', 'this.state=null'),
  'strategy':('this.strategy=strategy', 'this.strategy=new First()'),
  'template-method':('this.step();', ''),
  'visitor':('visitor.visit(this)', 'visitor.visit(null)'),
 },
 'typescript': {
  'abstract-factory':('return new Two()', 'throw new Error()'),
  'adapter':('return this.service.perform()', 'return 0'),
  'bridge':('return this.driver.run()', 'return 0'),
  'builder':('new Product(this.value)', 'new Product(123)'),
  'chain-of-responsibility':('if(request){this.following.run(request);}', 'this.following.run(request);'),
  'command':('command.execute();', ''),
  'composite':('child.run();', ''),
  'decorator':('console.log("before");', ''),
  'facade':('this.two.run();', ''),
  'factory-method':('return new Product()', 'throw new Error()'),
  'flyweight':('new Product(key)', 'new Product(0)'),
  'interpreter':('this.child.evaluate(context)', 'this.child.evaluate(0)'),
  'iterator':('yield* values;', 'return values;'),
  'mediator':('this.two.act();', ''),
  'memento':('this.value=snapshot.value', 'this.value=0'),
  'observer':('this.listeners.push(listener);', ''),
  'prototype':('new Subject(this.value)', 'new Subject(0)'),
  'proxy':('if(allowed){return this.inner.run(allowed);}return 0;', 'return this.inner.run(allowed);'),
  'singleton':('if(Subject.instance===null)', 'if(true)'),
  'state':('this.state=new Concrete()', 'this.state=this.state'),
  'strategy':('this.strategy=strategy', 'this.strategy=new First()'),
  'template-method':('this.step();', ''),
  'visitor':('visitor.visit(this)', 'visitor.visit(new Subject())'),
 },
}
# A branch must actually disappear; a constant condition is still a syntactic
# branch (constant folding is outside this IR's contract).
MUTATIONS['java']['chain-of-responsibility'] = ('if(request){this.following.run(request);}', 'this.following.run(request);')


@pytest.mark.parametrize('language', sorted(SOURCES))
@pytest.mark.parametrize('name', sorted(PYTHON))
def test_similar_collaboration_without_defining_behavior(language, name):
    source = SOURCES[language][name]
    old, new = MUTATIONS[language][name]
    assert old in source
    assert not evaluate(source.replace(old,new), language,name), (language,name)
