"""Construction access is lexical evidence, not runtime or whole-world exclusivity."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule
from ken.structural.query import QueryBudget

LANGUAGES=['java','csharp','typescript']
SOURCES={
 'java':'class Shared{private static final Shared value=new Shared();private Shared(){}static Shared get(){return value;}}',
 'csharp':'class Shared{private static readonly Shared value=new Shared();private Shared(){}static Shared get(){return value;}}',
 'typescript':'class Shared{private static readonly value=new Shared();private constructor(){}static get(){return Shared.value;}}',
}
POSITIVE={'positive','renamed','comments','overloads','unrelated-allocation'}
NEGATIVE={'public','protected','missing-constructor','factory','reset','second-field','nested-factory','parameter-private','comment-private'}
CASES=sorted(POSITIVE|NEGATIVE)


def source(language,change='positive'):
    text=SOURCES[language];ctor='private constructor(){}' if language=='typescript' else 'private Shared(){}'
    if change=='renamed':text=text.replace('Shared','Registry').replace('value','stored').replace('get()','acquire()')
    if change=='comments':text=text.replace(ctor,ctor.replace('private','/* public */private/* protected */'))
    if change in {'public','protected'}:text=text.replace(ctor,ctor.replace('private',change))
    if change=='missing-constructor':text=text.replace(ctor,'')
    if change in {'parameter-private','comment-private'}:
        replacement='constructor(private x:number){}' if change=='parameter-private' and language=='typescript' else ('public Shared(int privateValue){}' if change=='parameter-private' else '/* private */public Shared(){}')
        if language=='typescript' and change=='comment-private':replacement='/* private */constructor(){}'
        text=text.replace(ctor,replacement)
    if change=='overloads':
        replacement=ctor+('private constructor(x:number);' if language=='typescript' else 'private Shared(int x){}')
        if language=='typescript':replacement='private constructor();private constructor(x:number);private constructor(x?:number){}'
        text=text.replace(ctor,replacement)
    if change in {'factory','reset','nested-factory'}:
        method='static Shared fresh(){return new Shared();}' if language in {'java','csharp'} else 'static fresh(){return new Shared();}'
        if change=='reset':method=('static void reset(){value=new Shared();}' if language in {'java','csharp'} else 'static reset(){Shared.value=new Shared();}')
        if change=='nested-factory':method=('class Nested{'+method+'}') if language in {'java','csharp'} else 'static nested=class Nested{'+method+'};'
        text=text[:-1]+method+'}'
    if change=='second-field':text=text[:-1]+('static Shared second=new Shared();' if language in {'java','csharp'} else 'static second=new Shared();')+'}'
    if change=='unrelated-allocation':text+='class Other{'+('static Other item=new Other();' if language in {'java','csharp'} else 'static item=new Other();')+'}'
    return text


def search(text,language,rule='singleton',extra=(),budget=None):
    g=IR.from_dict(link_project([lower_source(text,language,'unit')]+[lower_source(s,language,p) for p,s in extra]).to_dict())
    rules=builtin_rules();q=named_rule(rule,rules) if isinstance(rule,str) else rule
    out=execute_rules(g,[q],budget,registry=rules);assert out['complete'];return g,out


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_restricted_eager_and_broad_operation_have_different_contracts(language,case):
    s=source(language,case);g,out=search(s,language);assert not g.diagnostics
    assert bool(out['matches'])==(case in POSITIVE)
    _,broad=search(s,language,'singleton.shared_instance');assert len(broad['matches'])==1


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('visibility',['public','private','protected','default'])
def test_constructor_visibility_is_queryable(language,visibility):
    s=source(language);ctor='private constructor' if language=='typescript' else 'private Shared('
    s=s.replace(ctor,ctor.replace('private ','' if visibility=='default' else visibility+' '))
    g,_=search(s,language);c=next(e for e in g.entities.values() if e.kind=='CALLABLE' and e.attrs.get('instance_constructor'))
    expected=visibility if visibility!='default' else {'java':'package','csharp':'private','typescript':'public'}[language]
    assert c.attrs['visibility']==expected and c.attrs['visibility_status']=='supported'
    q=SavedRule('access',f'query access {{callable(instance_constructor:true,visibility:{expected},visibility_status:supported) as $ctor;emit $ctor;}}')
    _,out=search(s,language,q);assert len(out['matches'])==1
    inventory=next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY')
    assert inventory.object=='supported' and inventory.attrs['explicit']==1
    assert inventory.attrs['private']==int(expected=='private')


@pytest.mark.parametrize('language',LANGUAGES)
def test_default_visibility_changes_canonical_acceptance(language):
    text=source(language).replace('private constructor','constructor').replace('private Shared()','Shared()')
    _,out=search(text,language);assert bool(out['matches'])==(language=='csharp')


@pytest.mark.parametrize('language',LANGUAGES)
def test_a_public_overload_is_not_hidden_by_a_private_constructor(language):
    text=source(language,'overloads')
    text=text.replace('private constructor(x:number)','public constructor(x:number)') if language=='typescript' else text.replace('private Shared(int x)','public Shared(int x)')
    g,out=search(text,language);assert not out['matches']
    inventory=next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY')
    assert inventory.attrs['other']==1


@pytest.mark.parametrize('language',['java','csharp'])
def test_annotation_arguments_do_not_supply_private_visibility(language):
    annotation='@Access("private") ' if language=='java' else '[Access("private")] '
    s=source(language).replace('private Shared(){}',annotation+'public Shared(){}')
    g,out=search(s,language);assert not g.diagnostics and not out['matches']


@pytest.mark.parametrize('modifier',['public','protected','internal','protected internal','private protected'])
def test_csharp_combined_access_is_not_plain_private(modifier):
    s=source('csharp').replace('private Shared()',modifier+' Shared()')
    g,out=search(s,'csharp');assert not out['matches']
    c=next(e for e in g.entities.values() if e.attrs.get('instance_constructor'))
    assert c.attrs['visibility']==' '.join(sorted(modifier.split()))


@pytest.mark.parametrize('change',['partial','primary','record','parse-error'])
def test_unsupported_constructor_surfaces_do_not_look_closed(change):
    s=source('csharp')
    if change=='partial':s=s.replace('class Shared','partial class Shared')
    elif change=='primary':s=s.replace('class Shared','class Shared(int number)')
    elif change=='record':s=s.replace('class Shared','record Shared')
    else:s=s[:-1]+' ??? }'
    g,out=search(s,'csharp');assert not out['matches']
    assert next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY').object=='unsupported'


@pytest.mark.parametrize('private',['private ',''])
def test_csharp_static_constructor_is_not_an_instance_constructor(private):
    s=source('csharp').replace('private Shared(){}',private+'Shared(){}static Shared(){}')
    g,out=search(s,'csharp');assert len(out['matches'])==1
    inv=next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY');assert inv.attrs['explicit']==1


def test_static_constructor_without_instance_declaration_is_not_private_construction():
    s=source('csharp').replace('private Shared(){}','static Shared(){}')
    g,out=search(s,'csharp');assert not out['matches']
    assert next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY').attrs['explicit']==0


@pytest.mark.parametrize('language',LANGUAGES)
def test_resolved_allocations_from_other_files_are_counted(language):
    # Explicit same-file type declarations are resolved by the existing linker.
    # Put the type and consumer in a single source for Java/C# and use imports for TS.
    if language=='typescript':
        s=source(language).replace('class Shared','export class Shared');extra=[('use.ts','import {Shared} from "./unit";function fresh(){return new Shared();}')]
        g,out=search(s,language,extra=extra)
    else:
        s=source(language)+'class Client{Shared fresh(){return new Shared();}}';g,out=search(s,language)
    assert not out['matches']
    assert any(f.relation=='RESOLVED_ALLOCATION_COUNT' and f.attrs['count']==2 for f in g.facts)


def test_opaque_constructor_alias_is_an_explicit_inventory_limit():
    s=source('typescript')+'const Alias=Shared;function fresh(){return new Alias();}'
    g,out=search(s,'typescript');assert len(out['matches'])==1
    assert next(f for f in g.facts if f.relation=='RESOLVED_ALLOCATION_COUNT').attrs['basis']=='explicit-resolved-sites'


def test_many_private_overloads_keep_the_query_bounded():
    s=''.join(source('java','overloads').replace('Shared',f'T{i}') for i in range(100))
    _,out=search(s,'java',budget=QueryBudget(max_matches=150,max_states=25000,max_rows=25000,timeout_ms=5000));assert len(out['matches'])==100


@pytest.mark.parametrize('language',LANGUAGES)
def test_interface_default_access_is_public(language):
    text='interface Contract{void run();}' if language in {'java','csharp'} else 'interface Contract{run():void;}'
    g=link_project([lower_source(text,language,'contract')]);assert not g.diagnostics
    method=next(e for e in g.entities.values() if e.kind=='CALLABLE')
    assert method.attrs['visibility']=='public'
    assert not any(f.relation=='CONSTRUCTOR_INVENTORY' for f in g.facts)


def test_java_method_named_constructor_is_not_a_constructor_declaration():
    g,_=search(source('java')[:-1]+'public void constructor(){}}','java')
    inv=next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY');assert inv.attrs['explicit']==1


@pytest.mark.parametrize('declaration',['static constructor(){}','get constructor(){return 1;}'])
def test_typescript_static_or_getter_named_constructor_is_not_an_instance_constructor(declaration):
    s=source('typescript').replace('private constructor(){}',declaration)
    g,out=search(s,'typescript');assert not out['matches']
    assert next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY').attrs['explicit']==0


@pytest.mark.parametrize('language',LANGUAGES)
def test_syntax_error_does_not_certify_the_constructor_inventory(language):
    s=source(language)[:-1]+' ??? }';g,out=search(s,language);assert g.diagnostics and not out['matches']
    assert next(f for f in g.facts if f.relation=='CONSTRUCTOR_INVENTORY').object=='unsupported'
