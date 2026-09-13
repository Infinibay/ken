"""Implicit reference defaults recover lazy patterns without inventing null in other languages."""
import pytest
from .test_lazy_null_flow import source as lazy_source, search

LANGUAGES=['java','csharp']
POSITIVE={'implicit','explicit','renamed','early-return','negative-else','private-constructor','comments','object-type'}
NEGATIVE={'wrong-polarity','force-or','reset-before','reset-after','historical-null','primitive','explicit-nonnull','duplicate-declaration'}
CASES=sorted(POSITIVE|NEGATIVE)


def source(language,case):
    base=case if case in {'early-return','negative-else','wrong-polarity','force-or','reset-before','reset-after','historical-null'} else 'positive'
    s=lazy_source(language,base)
    if case!='explicit':s=s.replace('static Shared value=null','static Shared value',1)
    if case=='renamed':s=s.replace('Shared','Registry').replace('value','cached').replace('get()','acquire()')
    if case=='private-constructor':s=s.replace('class Shared{','class Shared{private Shared(){}')
    if case=='comments':s=s.replace('Shared value','Shared /* null is implicit */ value')
    if case=='object-type':s=s.replace('Shared value',('Object' if language=='java' else 'object')+' value')
    if case=='primitive':s=s.replace('Shared value','int value')
    if case=='explicit-nonnull':s=s.replace('Shared value;','Shared value=new Other();')+'class Other{}'
    if case=='duplicate-declaration':s=s.replace('Shared value;','Shared value;static Shared value=null;')
    return s


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',CASES)
def test_reference_field_default_matches_only_the_correct_lazy_flow(language,case):
    g,out=search(source(language,case),language);assert not g.diagnostics
    assert bool(out['matches'])==(case in POSITIVE)


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_missing_initializer_does_not_mean_null_in_other_languages(language):
    s=lazy_source(language)
    if language=='python':s=s.replace('value = None','value: Shared',1)
    else:s=s.replace('static value=null','static value',1)
    _,out=search(s,language);assert not out['matches']


@pytest.mark.parametrize('language',LANGUAGES)
def test_write_in_a_method_does_not_replace_declaration_default_evidence(language):
    s=source(language,'implicit')[:-1]+'static void reset(){Shared.value=null;}}'
    g,out=search(s,language);assert len(out['matches'])==1
    slot=next(e.id for e in g.entities.values() if e.name=='value' and e.kind=='STORAGE')
    facts=[f for f in g.facts if f.subject==slot and f.relation=='FIELD_INITIAL_VALUE']
    assert len(facts)==1 and facts[0].attrs['basis']=='language-field-default'
