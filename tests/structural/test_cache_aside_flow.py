"""Null-miss read/load/write/return paths require current, correlated bindings."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules
from ken.structural.model import IR
from .test_cache_aside import SOURCES

CASES=['positive','renamed','alias-return','miss-return','ttl-option','logging',
       'write-before-load','key-before-test','key-after-load','key-after-write',
       'cache-rebound','value-before-test','value-after-load','value-after-write',
       'value-after-branch','return-before-load','return-before-write','wrong-return']
POSITIVES={'positive','renamed','alias-return','miss-return','ttl-option','logging'}


def source(language,case):
    text=SOURCES[language]
    py=language=='python';cs=language=='csharp';js=language in {'javascript','typescript'}
    load='value = source.load(key)';write='cache.'+('Set' if cs else 'set')+'(key, value)'
    inner='\n  ' if py else '; '
    outer='\n ' if py else '; '
    statement=load+(inner if py else '; ')+write
    null='None' if py else 'null'
    if case=='renamed':
        return text.replace('cache','memo').replace('source','repository').replace('key','token').replace('value','item')
    if case=='alias-return':
        declaration='' if py else 'let ' if js else 'var ' if cs else 'Object '
        return text.replace('return value',declaration+'result = value'+outer+'return result')
    if case=='miss-return':
        return text.replace(write,write+inner+'return value')
    if case=='ttl-option':return text.replace('(key, value)','(key, value, 300)')
    if case=='logging':return text.replace('return value','log(value)'+outer+'return value')
    if case=='write-before-load':
        assert statement in text
        return text.replace(statement,write+inner+load)
    if case=='key-before-test':
        return text.replace((' if value' if py else 'if (value'),(' key = other\n if value' if py else 'key = other; if (value'))
    replacements={
      'key-after-load':(load,load+inner+'key = other'),
      'key-after-write':(write,write+inner+'key = other'),
      'cache-rebound':(load,'cache = other'+inner+load),
      'value-before-test':((' if value' if py else 'if (value'),(' value = '+null+'\n if value' if py else 'value = null; if (value')),
      'value-after-load':(load,load+inner+'value = '+null),
      'value-after-write':(write,write+inner+'value = '+null),
      'value-after-branch':('return value','value = '+null+outer+'return value'),
      'return-before-load':(load,'return value'+inner+load),
      'return-before-write':(write,'return value'+inner+write),
      'wrong-return':('return value','return other'),
    }
    if case in replacements:
        a,b=replacements[case];assert a in text;text=text.replace(a,b)
    return text


def detect(text,language):
    graph=link_project([lower_source(text,language,'null-flow')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    rules=builtin_rules();out=execute_rules(graph,[named_rule('architecture.cache-aside#null-miss',rules)],registry=rules)
    assert out['complete'],out
    assert all(m['status']=='structural_match' for m in out['matches']),out
    return graph,out


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('case',CASES)
def test_order_and_current_bindings(language,case):
    _,out=detect(source(language,case),language)
    assert bool(out['matches'])==(case in POSITIVES),out


@pytest.mark.parametrize('language',['python','javascript','typescript'])
@pytest.mark.parametrize('call',['get','load','set'])
def test_expanded_key_is_not_a_scalar_key(language,call):
    text=source(language,'positive');spread='*key' if language=='python' else '...key'
    text=text.replace('.'+call+'(key','. '+call+'('+spread).replace('. '+call+'(','.'+call+'(')
    assert not detect(text,language)[1]['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_join_retains_possible_origins(language):
    graph,out=detect(source(language,'positive'),language);assert len(out['matches'])==1
    origins=[f for f in graph.facts if f.relation=='RETURN_ORIGIN']
    assert len(origins)==2 and {f.attrs['modality'] for f in origins}=={'may'}
    assert len({f.subject for f in origins})==1
