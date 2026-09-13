"""Direct class receivers select static declarations without inventing instances."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR

LANGUAGES=['java','csharp','javascript','typescript']

def source(language,change='positive'):
    typed=language in {'java','csharp'}
    method='static int compute(int value){return value;}' if typed else 'static compute(value){return value;}'
    use='int use(){return Provider.compute(1);}' if typed else 'use(){return Provider.compute(1);}'
    if change=='instance':method=method.replace('static ','')
    if change=='unknown':use=use.replace('Provider.compute','Missing.compute')
    if change=='other-method':use=use.replace('Provider.compute','Provider.other')
    if change=='shadow':use=use.replace('use()','use(Object Provider)' if typed else 'use(Provider)')
    if change=='bare-local':use=use.replace('return Provider','Object Provider;return Provider' if typed else 'let Provider;return Provider')
    if change=='private':method='private '+method if typed or language=='typescript' else method.replace('compute','#compute');use=use if typed or language=='typescript' else use.replace('.compute','.#compute')
    if change=='overloads':method+=method.replace('int value','String value' if language=='java' else 'string value').replace('return value;','return 1;') if typed else method
    if change=='renamed':method=method.replace('compute','acquire');use=use.replace('compute','acquire').replace('Provider','Catalog')
    name='Catalog' if change=='renamed' else 'Provider'
    text='class '+name+'{'+method+'}class Client{'+use+'}'
    if change=='inherited':text=('class Base{'+method+'}class Provider extends Base{}' if language in {'java','javascript','typescript'} else 'class Base{'+method+'}class Provider:Base{}')+'class Client{'+use+'}'
    return text


def graph(text,language):
    g=IR.from_dict(link_project([lower_source(text,language,'static')]).to_dict());assert not g.diagnostics;return g


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',['positive','instance','unknown','other-method','shadow','bare-local','private','overloads','renamed','inherited'])
def test_static_target_resolution_and_bounds(language,change):
    g=graph(source(language,change),language)
    links=[f for f in g.facts if f.relation=='TARGET' and f.attrs.get('basis')=='direct-class-static']
    possible=[f for f in g.facts if f.relation=='MAY_TARGET' and f.attrs.get('basis')=='direct-class-static']
    assert len(links)==(1 if change in {'positive','private','renamed'} else 0)
    assert len(possible)==(2 if change=='overloads' else 0)
    assert not any(f.relation=='DELEGATES_TYPE' for f in g.facts)
    for f in links:
        assert g.entities[f.object].attrs['static']
        assert any(c.relation=='CALLS' and c.object==f.object for c in g.facts)


@pytest.mark.parametrize('language',['javascript','typescript'])
@pytest.mark.parametrize('placement',['before','after'])
def test_static_field_can_shadow_a_method(language,placement):
    text=source(language)
    if placement=='before':text=text.replace('class Provider{','class Provider{static compute=(value)=>value;')
    else:text=text.replace('}class Client','static compute=(value)=>value;}class Client')
    g=graph(text,language);assert not any(f.relation in {'TARGET','MAY_TARGET'} for f in g.facts)


@pytest.mark.parametrize('language',['javascript','typescript'])
@pytest.mark.parametrize('kind',['get','set'])
def test_property_access_is_not_a_direct_method_invocation(language,kind):
    member='static get compute(){return (value)=>value;}' if kind=='get' else 'static set compute(value){}'
    text='class Provider{'+member+'}class Client{use(){return Provider.compute(1);}}'
    g=graph(text,language);assert not any(f.relation in {'TARGET','MAY_TARGET'} for f in g.facts)


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_property_and_method_collision_does_not_select_the_method(language):
    text=source(language).replace('}class Client','static get compute(){return (value)=>value;}}class Client')
    g=graph(text,language);assert not any(f.relation in {'TARGET','MAY_TARGET'} for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_instance_receiver_dispatch_is_preserved(language):
    typed=language in {'java','csharp'}
    text=source(language,'instance').replace('use()','use(Provider value)' if typed else 'use(value)')
    if not typed:text=text.replace('return Provider.compute','value=new Provider();return value.compute')
    else:text=text.replace('return Provider.compute','return value.compute')
    g=graph(text,language)
    assert len([f for f in g.facts if f.relation=='TARGET'])==1
    assert not any(f.attrs.get('basis')=='direct-class-static' for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_static_call_arguments_bind_to_the_explicit_parameter(language):
    g=graph(source(language),language)
    assert any(f.relation=='BINDS_TO' for f in g.facts)
    assert any(f.relation=='BINDING_STATUS' and f.object=='supported' for f in g.facts)
