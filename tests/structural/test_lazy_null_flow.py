"""Lazy initialization must follow the null arm, not merely mention the slot."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule
from ken.structural.model import IR
from ken.structural.query import QueryBudget

LANGUAGES=['python','java','javascript','typescript','csharp']
POSITIVE={'positive','renamed','null-left','comments','double-negative','negated-inequality','early-return','else-separated','negative-else'}
NEGATIVE={'wrong-polarity','negated-equality','force-or','other-guard','write-before','write-outside','reset-before','reset-after','hit-other-return','miss-other-return','historical-null','fresh-return','duplicate-write'}
CASES=sorted(POSITIVE|NEGATIVE)


def source(language,change='positive'):
    py=language=='python';v='cls.value' if py else 'Shared.value';null='None' if py else 'null'
    eq=' is ' if py else ' === ' if language in {'javascript','typescript'} else ' == '
    ne=' is not ' if py else ' !== ' if language in {'javascript','typescript'} else ' != '
    invert='not ' if py else '!';creation='Shared()' if py else 'new Shared()'
    condition=v+eq+null;write=v+' = '+creation;ret='return '+v
    if change=='null-left':condition=null+eq+v
    if change in {'wrong-polarity','early-return','negative-else'}:condition=v+ne+null
    if change=='negated-equality':condition=invert+'('+condition+')'
    if change=='negated-inequality':condition=invert+'('+v+ne+null+')'
    if change=='double-negative':condition=invert+'('+invert+'('+condition+'))'
    if change=='force-or':condition+=' or force' if py else ' || force'
    if change=='other-guard':condition=('cls.other' if py else 'Shared.other')+eq+null
    if py:
        body='if '+condition+':\n '+write+'\n'+ret
        if change=='early-return':body='if '+condition+':\n '+ret+'\n'+write+'\n'+ret
        if change=='else-separated':body='if '+condition+':\n '+write+'\n '+ret+'\nelse:\n '+ret
        if change=='negative-else':body='if '+condition+':\n '+ret+'\nelse:\n '+write+'\n '+ret
        if change=='write-before':body=write+'\nif '+condition+':\n pass\n'+ret
        if change=='write-outside':body='if '+condition+':\n pass\n'+write+'\n'+ret
        if change=='reset-before':body=v+' = None\n'+body
        if change=='reset-after':body=body.replace('\n'+ret,'\n'+v+' = None\n'+ret)
        if change=='hit-other-return':body='if '+condition+':\n '+write+'\n '+ret+'\nreturn None'
        if change=='miss-other-return':body='if '+condition+':\n '+write+'\n return None\n'+ret
        if change=='fresh-return':body=body.replace(ret,'return Shared()')
        if change=='duplicate-write':body=body.replace(write,write+'\n '+write)
        if change=='comments':body=body.replace(write,'# alternate public storage\n '+write)
        text='class Shared:\n value = None\n other = None\n @classmethod\n def get(cls):\n'+''.join('  '+line+'\n' for line in body.splitlines())
        if change=='historical-null':text=text.replace('value = None','value = 1',1)+' @classmethod\n def reset(cls): cls.value = None\n'
    else:
        write+=';';ret+=';';body='if('+condition+'){'+write+'}'+ret
        if change=='early-return':body='if('+condition+'){'+ret+'}'+write+ret
        if change=='else-separated':body='if('+condition+'){'+write+ret+'}else{'+ret+'}'
        if change=='negative-else':body='if('+condition+'){'+ret+'}else{'+write+ret+'}'
        if change=='write-before':body=write+'if('+condition+'){}'+ret
        if change=='write-outside':body='if('+condition+'){}'+write+ret
        if change=='reset-before':body=v+'=null;'+body
        if change=='reset-after':body=body.replace(ret,v+'=null;'+ret)
        if change=='hit-other-return':body='if('+condition+'){'+write+ret+'}return null;'
        if change=='miss-other-return':body='if('+condition+'){'+write+'return null;}'+ret
        if change=='fresh-return':body=body.replace(ret,'return new Shared();')
        if change=='duplicate-write':body=body.replace(write,write+write)
        if change=='comments':body=body.replace(write,'/* storage */'+write)
        field='static Shared value=null;static Shared other=null;' if language in {'java','csharp'} else 'static value=null;static other=null;'
        method='static Shared get()' if language in {'java','csharp'} else 'static get()'
        text='class Shared{'+field+method+'{'+body+'}}'
        if change=='historical-null':text=text.replace('value=null','value=new Other()',1)[:-1]+('static void reset()' if language in {'java','csharp'} else 'static reset()')+'{Shared.value=null;}}class Other{}'
    if change=='renamed':
        for a,b in [('Shared','Registry'),('value','stored'),('get','acquire')]:text=re.sub(r'\b'+a+r'\b',b,text)
    return text


def search(text,language,rule='singleton',budget=None):
    g=IR.from_dict(link_project([lower_source(text,language,'lazy')]).to_dict());rules=builtin_rules()
    q=named_rule(rule,rules) if isinstance(rule,str) else rule
    out=execute_rules(g,[q],budget,registry=rules);assert out['complete'];return g,out


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',CASES)
def test_null_arm_controls_initialization_and_both_returns(language,change):
    g,out=search(source(language,change),language);assert not g.diagnostics
    assert bool(out['matches'])==(change in POSITIVE)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',['logging','alias','nested-condition'])
def test_logging_preserves_initialization_but_alias_and_conditional_creation_are_excluded(language,change):
    s=source(language);v='cls.value' if language=='python' else 'Shared.value'
    if language=='python':
        if change=='logging':s=s.replace('   cls.value','   log()\n   cls.value')
        elif change=='alias':s=s.replace('  return cls.value','  result=cls.value\n  return result')
        else:s=s.replace('   cls.value','   if permitted:\n    cls.value')
    else:
        if change=='logging':s=s.replace('{Shared.value =','{log();Shared.value =')
        elif change=='alias':s=s.replace('return Shared.value;',('Shared' if language in {'java','csharp'} else 'const')+' result=Shared.value;return result;')
        else:s=s.replace('{Shared.value = new Shared();}','{if(permitted){Shared.value = new Shared();}}')
    _,out=search(s,language);assert bool(out['matches']) == (change == 'logging')


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',['log-before-write','log-before-hit-return','conditional-write'])
def test_early_return_requires_unconditional_missing_initialization(language,change):
    s=source(language,'early-return')
    if language=='python':
        if change=='log-before-write':
            s=s.replace('  cls.value = Shared()', '  log()\n  cls.value = Shared()')
        elif change=='log-before-hit-return':
            s=s.replace('   return cls.value', '   log()\n   return cls.value')
        else:
            s=s.replace('  cls.value = Shared()', '  if permitted:\n   cls.value = Shared()')
    else:
        if change=='log-before-write':
            s=s.replace('}Shared.value = new Shared();', '}log();Shared.value = new Shared();')
        elif change=='log-before-hit-return':
            s=s.replace('{return Shared.value;}', '{log();return Shared.value;}')
        else:
            s=s.replace('}Shared.value = new Shared();', '}if(permitted){Shared.value = new Shared();}')
    g,out=search(s,language);assert not g.diagnostics
    assert bool(out['matches']) == (change != 'conditional-write')


@pytest.mark.parametrize('language',LANGUAGES)
def test_named_lazy_operation_exposes_correlated_roles(language):
    q=SavedRule('usage','''query usage {
      match "singleton.lazy_instance"(unit:$unit,storage:$storage,accessor:$accessor,creation:$creation);
      require $unit HAS_METHOD $accessor;
      require $creation ALLOCATES_TYPE $unit;
      emit $unit,$storage,$accessor,$creation;
    }''')
    g,out=search(source(language),language,q);assert len(out['matches'])==1
    roles=out['matches'][0]['bindings'];assert g.entities[roles['$unit']].name=='Shared'
    # Nonlocal storage writes remain outside RETURN_ORIGIN's local-flow guarantee.
    assert any(f.subject==roles['$accessor'] and f.relation=='RETURN_FLOW_STATUS' and f.object=='unsupported' for f in g.facts)


@pytest.mark.parametrize('language',['java','javascript','typescript','csharp'])
def test_nonstatic_storage_is_not_a_lazy_class_instance(language):
    s=source(language).replace('static ','',1);_,out=search(s,language);assert not out['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_parsing_errors_do_not_prove_lazy_flow(language):
    s=source(language)+' ???';g,out=search(s,language);assert g.diagnostics and not out['matches']


def test_lazy_join_budget_with_many_candidates():
    # Source BODY budgets charge CFG traversal/provenance as well as relational
    # rows. Compare scaling explicitly instead of retaining a graph-only 25k
    # budget that counted a different unit of work.
    costs=[]
    for count in (100,200):
        s=''.join(source('java').replace('Shared',f'T{i}') for i in range(count))
        _,out=search(s,'java','singleton.lazy_instance',QueryBudget(
            max_matches=count+10,max_states=count*1000,max_rows=count*250,timeout_ms=5000))
        assert len(out['matches'])==count
        costs.append(out['outcomes']['singleton.lazy_instance']['stats']['states'])
    assert costs[1] <= costs[0]*2.2
