"""Runtime base references are distinct from nominal inheritance spelling."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule
from ken.structural.query import QueryBudget

LANGUAGES=['python','javascript','typescript']
POSITIVE={'positive','renamed','local-alias','empty-class','constructor','nominal-shadow','branch-return'}
NEGATIVE={'constant-base','no-base','return-instance','no-return','other-return','input-before'}
CHANGES=sorted(POSITIVE|NEGATIVE)


def source(language,change='positive'):
    if language=='python':
        text='def extend(base):\n class Derived(base):\n  def render(self): return 1\n return Derived\n'
        if change=='local-alias':text=text.replace('return Derived','result=Derived\n return result')
        if change=='empty-class':text=text.replace('def render(self): return 1','pass')
        if change=='constructor':text=text.replace('def render(self): return 1','def __init__(self,*args,**kwargs): super().__init__(*args,**kwargs)')
        if change=='branch-return':text=text.replace('return Derived','if flag: return Derived\n return Derived')
        if change=='constant-base':text='class Other: pass\n'+text.replace('Derived(base)','Derived(Other)')
        if change=='no-base':text=text.replace('Derived(base)','Derived')
        if change=='return-instance':text=text.replace('return Derived','return Derived()')
        if change=='no-return':text=text.replace(' return Derived\n','')
        if change=='other-return':text=text.replace('return Derived','return base')
        if change=='input-before':text='class Other: pass\n'+text.replace('class Derived(base)','base=Other\n class Derived(base)')
        if change=='nominal-shadow':text='class base: pass\n'+text
    else:
        prefix='function extend(base)' if language=='javascript' else 'type Constructor=new(...args:any[])=>{};function extend<T extends Constructor>(base:T)'
        body='return class Derived extends base{render(){return 1;}};'
        if change=='local-alias':body='const result=class Derived extends base{render(){return 1;}};return result;'
        if change=='empty-class':body='return class extends base{};'
        if change=='constructor':body='return class extends base{constructor(...args'+(':any[]' if language=='typescript' else '')+'){super(...args);}};'
        if change=='branch-return':body='const result=class extends base{};if(flag){return result;}return result;'
        if change=='constant-base':body=body.replace('extends base','extends Other')
        if change=='no-base':body=body.replace(' extends base','')
        if change=='return-instance':body='const Result=class extends base{};return new Result();'
        if change=='no-return':body='const Result=class extends base{};'
        if change=='other-return':body='const Result=class extends base{};return base;'
        if change=='input-before':body='base=Other;'+body
        text=prefix+'{'+body+'}'
        if change in {'constant-base','input-before'}:text='class Other{}'+text
        if change=='nominal-shadow':text='class base{}'+text
    if change=='renamed':
        for a,b in [('extend','withTracing'),('base','Component'),('Derived','Traced')]:text=re.sub(r'\b'+a+r'\b',b,text)
    return text


def search(text,language,rule='architecture.subclass-factory',budget=None):
    g=link_project([lower_source(text,language,'mixin')]);assert not g.diagnostics
    registry=builtin_rules();q=named_rule(rule,registry) if isinstance(rule,str) else rule
    out=execute_rules(g,[q],budget,registry=registry);assert out['complete'];return g,out


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',CHANGES)
def test_supplied_base_factories_and_near_misses(language,change):
    _,out=search(source(language,change),language);assert bool(out['matches'])==(change in POSITIVE)


@pytest.mark.parametrize('language',LANGUAGES)
def test_parameter_base_is_not_a_same_spelled_nominal_class(language):
    g,out=search(source(language,'nominal-shadow'),language);assert len(out['matches'])==1
    derived=out['matches'][0]['bindings']['$derived']
    assert not any(f.relation=='SUBTYPE_OF' and f.subject==derived for f in g.facts)
    assert any(f.relation=='BASE_NAME' and f.subject==derived for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_unique_preceding_base_alias_preserves_supplied_base(language):
    text=source(language)
    if language=='python':text=text.replace('class Derived(base)','selected=base\n class Derived(selected)')
    else:text=text.replace('{return class','{const selected=base;return class').replace('extends base','extends selected')
    _,out=search(text,language);assert out['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_parameter_write_after_definition_is_conservatively_excluded(language):
    text=source(language,'local-alias')
    if language=='python':text=text.replace('return result','base=None\n return result')
    else:text=text.replace('return result','base=null;return result')
    _,out=search(text,language);assert not out['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_returning_a_class_from_another_factory_does_not_cross_roles(language):
    text=source(language)
    if language=='python':text+='def unrelated(other):\n return extend(other)\n'
    else:text+='function unrelated(other){return extend(other);}'
    g,out=search(text,language);assert len(out['matches'])==1
    assert g.entities[out['matches'][0]['bindings']['$factory']].name=='extend'


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_arrow_factory_returns_a_class_value(language):
    text='const extend=(base)=>class extends base{render(){return 1;}};'
    _,out=search(text,language);assert len(out['matches'])==1


@pytest.mark.parametrize('language',LANGUAGES)
def test_named_usage_query_exposes_the_factory_call(language):
    text=source(language)+ ('class Widget: pass\nextend(Widget)\n' if language=='python' else 'class Widget{}extend(Widget);')
    q=SavedRule('usage','''query usage {
      match "architecture.subclass-factory"(factory:$factory,derived:$derived,base:$base);
      require $call TARGET $factory;
      emit $factory,$derived,$base,$call;
    }''')
    _,out=search(text,language,q);assert len(out['matches'])==1


def test_subclass_factory_query_is_bounded_for_many_independent_factories():
    text=''.join(source('javascript').replace('function extend(',f'function extend{i}(') for i in range(150))
    _,out=search(text,'javascript',budget=QueryBudget(max_matches=200,max_states=10000,max_rows=10000,timeout_ms=5000));assert len(out['matches'])==150
