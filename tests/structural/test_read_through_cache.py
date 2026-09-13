"""Owned cache hit-return/miss-fill paths, with independently correlated roles."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules
from ken.structural.model import IR

LANGUAGES=['python','javascript','typescript','java','csharp']


def source(language,change='positive'):
    if language=='python':
        text='''class Memo: pass
class Provider:
 def __init__(self, external): self.cache=Memo()
 def read(self, source, key):
  if self.cache.contains(key):
   return self.cache.get(key)
  value=source.load(key)
  self.cache.set(key,value)
  return value
'''
        cache='self.cache';newline='\n  ';assignment='value=source.load(key)';write=cache+'.set(key,value)'
    else:
        js=language=='javascript';ts=language=='typescript';cs=language=='csharp'
        name='Get' if cs else 'get';contains='Contains' if cs else 'contains';setname='Set' if cs else 'set'
        if js or ts:
            fields='' if js else 'cache:Memo;'
            ctor='constructor(external)' if js else 'constructor(external:Memo)'
            read='read(source,key)' if js else 'read(source:Store,key:string)'
            declaration='let value=source.load(key)'
        else:
            fields='Memo cache;';ctor='public Provider(Memo external)'
            read=('object' if cs else 'Object')+' read(Store source,string key)' if cs else 'Object read(Store source,String key)'
            declaration=('var' if cs else 'Object')+' value=source.load(key)'
        text=f'''class Memo {{}} class Provider {{{fields}
 {ctor} {{this.cache=new Memo();}}
 {read} {{if(this.cache.{contains}(key)){{return this.cache.{name}(key);}}
 {declaration};this.cache.{setname}(key,value);return value;}}
}}'''
        cache='this.cache';newline=';';assignment=declaration;write=cache+'.'+setname+'(key,value)'
    load='source.load(key)';get=cache+('.Get(key)' if language=='csharp' else '.get(key)');contains=cache+('.Contains(key)' if language=='csharp' else '.contains(key)')
    changes={
      'other-lookup-key':(get,get.replace('(key)','(other)')),
      'other-load-key':(load,load.replace('(key)','(other)')),
      'other-write-key':(write,write.replace('(key,value)','(other,value)')),
      'other-write-value':(write,write.replace('(key,value)','(key,other)')),
      'other-cache':(write,write.replace(cache,'other')),
      'same-cache-loader':(load,load.replace('source',cache)),
      'key-rebound-before':(assignment,'key=other'+newline+assignment),
      'key-rebound-after':(write,write+newline+'key=other'),
      'cache-rebound':(assignment,cache+'=external'+newline+assignment),
      'value-overwritten':(write,'value=other'+newline+write),
      'value-reassigned-after':('return value','value=other'+newline+'return value'),
      'wrong-return':('return value','return other'),
      'hit-without-return':('return '+get,get),
      'write-before-load':(assignment+newline+write,write+newline+assignment),
      'borrowed-cache':(cache+('=Memo()' if language=='python' else '=new Memo()'),cache+'=external'),
      'negated-hit':(contains,('not '+contains if language=='python' else '!'+contains)),
      'disjunction':(contains,contains+(' or force' if language=='python' else ' || force')),
      'conjunction':(contains,contains+(' and force' if language=='python' else ' && force')),
    }
    if change in changes:
        a,b=changes[change];assert a in text,(language,change,a);text=text.replace(a,b)
    if change=='renamed':
        for a,b in [('Provider','StorageGateway'),('Memo','Buffer'),('source','repository'),('key','token'),('value','item'),('cache','memo')]:text=text.replace(a,b)
    if change=='alternate-api':text=text.replace('.contains(','.containsKey(').replace('.Contains(','.ContainsKey(').replace('.set(','.put(')
    return text


def run(text,language,operation=False):
    graph=link_project([lower_source(text,language,'read-fill')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    rules=builtin_rules();id='architecture.read-through-cache'+('.read_fill' if operation else '')
    out=execute_rules(graph,[named_rule(id,rules)],registry=rules);assert out['complete'],out
    assert all(m['status']=='structural_match' for m in out['matches']),out
    return out


CHANGES=['positive','renamed','alternate-api','other-lookup-key','other-load-key','other-write-key','other-write-value','other-cache','same-cache-loader','key-rebound-before','key-rebound-after','cache-rebound','value-overwritten','value-reassigned-after','wrong-return','hit-without-return','write-before-load','borrowed-cache','negated-hit','disjunction','conjunction']
@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',CHANGES)
def test_read_through_paths_and_near_misses(language,change):
    out=run(source(language,change),language)
    assert bool(out['matches'])==(change in {'positive','renamed','alternate-api'}),out


@pytest.mark.parametrize('language',LANGUAGES)
def test_public_usage_does_not_assert_cache_ownership(language):
    out=run(source(language,'borrowed-cache'),language,operation=True)
    assert len(out['matches'])==1,out


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('change',['wrong-hit-cache','load-after-return','write-after-return','extra-presence-argument','extra-write-argument'])
def test_additional_control_and_call_shapes(language,change):
    text=source(language);cache='self.cache' if language=='python' else 'this.cache'
    newline='\n  ' if language=='python' else ';'
    if change=='wrong-hit-cache':text=text.replace(cache+'.get(key)','other.get(key)').replace(cache+'.Get(key)','other.Get(key)')
    elif change=='load-after-return':
        # An unreachable loader cannot be reached from the false edge.
        if language=='python':text=text.replace('  value=source.load(key)','  return other\n  value=source.load(key)')
        else:text=text.replace('let value=source.load(key)','return other;let value=source.load(key)').replace('Object value=source.load(key)','return other;Object value=source.load(key)').replace('var value=source.load(key)','return other;var value=source.load(key)')
    elif change=='write-after-return':text=text.replace(cache+'.set(key,value)','return value'+newline+cache+'.set(key,value)').replace(cache+'.Set(key,value)','return value'+newline+cache+'.Set(key,value)')
    elif change=='extra-presence-argument':text=text.replace('.contains(key)','.contains(key,other)').replace('.Contains(key)','.Contains(key,other)')
    else:text=text.replace('(key,value)','(key,value,other)')
    assert not run(text,language)['matches']


@pytest.mark.parametrize('language',['python','javascript','typescript'])
@pytest.mark.parametrize('position',['presence','lookup','load','write'])
def test_expanded_key_is_not_a_scalar_cache_key(language,position):
    text=source(language);spread='*key' if language=='python' else '...key'
    old={'presence':'.contains(key)','lookup':'.get(key)','load':'.load(key)','write':'.set(key,value)'}[position]
    text=text.replace(old,old.replace('key',spread))
    assert not run(text,language)['matches']
