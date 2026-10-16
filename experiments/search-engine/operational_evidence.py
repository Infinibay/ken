"""Source role, explicit code references and operation cues, never relevance labels.

These are lexical/structural ranking cues, not a proof of behavior or dispatch.
All caller data comes from authenticated canonical source owners.
"""
import re
from functools import lru_cache
import numpy as np
from ken.retrieval.tokenization import code_tokens
from ken.retrieval.owner_ranking import EvidenceReranker


def critical_references(query):
    refs=[]
    for value in re.findall(r'`([^`]+)`',query):
        if re.fullmatch(r'[\w$/.-]+(?:::[\w$.]+)?',value):refs.append(value.split('::')[-1])
    for token in re.findall(r'\b[A-Za-z_][A-Za-z_0-9]*\b',re.sub(r'`[^`]+`','',query)):
        if (re.search(r'[a-z][A-Z]',token) or re.fullmatch(r'[A-Z][A-Z_0-9]+',token)
                or '_' in token and len(token.strip('_'))>1):refs.append(token)
    return list(dict.fromkeys(refs))


def reference_coverage(refs,executable,extra='',*,qualname=''):
    if not refs:return 0.,0.
    text=executable+'\n'+extra
    present=sum(bool(re.search(r'(?<![\w$])'+re.escape(r)+r'(?![\w$])',text,re.I)) for r in refs)
    identity=sum(r.casefold()==qualname.casefold() or r.casefold()==qualname.rsplit('.',1)[-1].casefold() for r in refs)
    return present/len(refs),identity/len(refs)


def test_entrypoint(name,prelude,*,file_test,nested_callable):
    if nested_callable:return False
    leaf=name.rsplit('.',1)[-1]
    return bool(file_test and leaf.startswith('test_') or re.search(
        r'(?m)^\s*@(?:[\w.]+\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate|Theory)\b',prelude))


_GROUPS={
 'branch':'if when unless otherwise whether conditional choose fallback branch case',
 'mutation':'append insert remove delete clear add set store save cache record update assign mutate',
 'exception':'raise throw catch reject fail exception error',
 'loop':'loop iterate repeat each every repeatedly scan',
 'call':'call invoke execute run apply dispatch delegate callback',
 'return':'return yield',
}
_ACTIONS='append insert remove delete clear add set store save cache record update assign return yield raise throw catch compare equal apply invoke call execute run merge split join select parse match read write load dump sort convert validate check'
@lru_cache(maxsize=1)
def _terms():
    groups={k:set(EvidenceReranker.stem_words(v.split())) for k,v in _GROUPS.items()}
    return groups,set(EvidenceReranker.stem_words(_ACTIONS.split()))


def operation_alignment(query,executable,calls,*,test_query=False):
    groups,actions=_terms();q=set(EvidenceReranker.stem_words(code_tokens(query)));c=set(EvidenceReranker.stem_words(code_tokens(calls)))
    asked=np.array([bool(q&words) for words in groups.values()],dtype=float)
    observed=np.array([
        bool(re.search(r'\b(?:if|else|switch|case|match)\b|&&|\|\||\?[^\n]+:',executable)),
        bool(re.search(r'(?<![=!<>])=(?!=|>)|\+=|-=|\+\+|--',executable)) or bool(c&groups['mutation']),
        bool(re.search(r'\b(?:raise|throw|except|catch)\b',executable)) or bool(c&groups['exception']),
        bool(re.search(r'\b(?:for|while)\b',executable)) or bool(c&{'foreach','map'}),
        bool(calls.strip()),
        bool(re.search(r'\b(?:return|yield)\b',executable)),
    ],dtype=float)
    matching=asked*observed/max(1.,asked.sum())
    requested_actions=q&actions;call_overlap=len(requested_actions&c)/max(1,len(requested_actions))
    return np.r_[matching,matching*float(test_query),call_overlap]
