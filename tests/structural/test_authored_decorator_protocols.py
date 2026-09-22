"""Source macro, SAM and base-dispatch semantics used by Decorator."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,execute_rules,named_rule
from .test_catalog_adversarial_matrix import CASES


def detect(source,language,rule):
    graph=link_project([lower_source(source,language,'case.'+language)])
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule(rule,registry)],registry=registry)
    assert result['complete'],result
    return graph,result


@pytest.mark.parametrize('language',['python','java','typescript','csharp'])
@pytest.mark.parametrize('mutation',['positive','no_base_call','wrong_method'])
def test_subclass_responsibility_requires_real_forwarding(language,mutation):
    case=next(c for c in CASES if c.id==f'decorator#subclass-addition/{language}/canonical')
    source=case.source
    spelling={'python':'super().run()','java':'super.run()','typescript':'super.run()','csharp':'base.Run()'}[language]
    source=source.replace(spelling,'0' if mutation=='no_base_call' else spelling.replace('run','other').replace('Run','Other') if mutation=='wrong_method' else spelling)
    _,result=detect(source,language,'decorator#subclass-addition')
    assert bool(result['matches']) is (mutation=='positive')


@pytest.mark.parametrize('shadow',['parameter','local','module','multiple'])
def test_python_super_is_not_guessed_when_shadowed_or_ambiguous(shadow):
    source='class Base:\n def run(self): return 1\nclass Child(Base):\n def run(self): return super().run()\n'
    if shadow=='parameter':source=source.replace('class Child(Base):\n def run(self):','class Child(Base):\n def run(self,super):')
    if shadow=='local':source=source.replace('def run(self): return super().run()','def run(self):\n  super = other\n  return super().run()')
    if shadow=='module':source='def super(): return other\n'+source
    if shadow=='multiple':source=source.replace('class Child(Base):','class Child(Base,Missing):')
    compile(source,'p.py','exec')
    graph=link_project([lower_source(source,'python','p.py')])
    base=next(e.id for e in graph.entities.values() if e.kind=='CALLABLE' and '/CLASS:Base/' in e.id)
    assert not [f for f in graph.facts if f.relation=='TARGET' and f.object==base]


@pytest.mark.parametrize('interface,expected',[
 ('interface Action {int run(int value);}',True),
 ('interface Action {int run(int value); void close();}',False),
 ('interface Action {default int run(int value){return value;}}',False),
 ('interface Action {int run(int value); default void close(){}}',True),
])
def test_java_functional_slot_requires_single_abstract_method(interface,expected):
    source=interface+'class Factory {static Action traced(Action inner){return value->{System.out.println("trace");return inner.run(value);};}}'
    _,result=detect(source,'java','decorator#callable-wrapper')
    assert bool(result['matches']) is expected
