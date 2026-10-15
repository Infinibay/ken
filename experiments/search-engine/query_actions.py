"""Retain grammatical action evidence without rewriting the original request."""
from __future__ import annotations
from collections.abc import Callable,Sequence
from dataclasses import dataclass

AUXILIARIES=frozenset('am is are was were be being been have has had having do does did doing'.split())
VERBS=frozenset(('VB','VBD','VBG','VBN','VBP','VBZ'))


@dataclass(frozen=True)
class QueryActions:
    tokens: tuple[str,...]
    actions: tuple[str,...]


def extract_actions(query: str, *, tokenize: Callable[[str],list[str]],
                    tag: Callable[[list[str]],Sequence[tuple[str,str]]]) -> QueryActions:
    tokens=tuple(tokenize(query))
    if any(not isinstance(t,str)or not t for t in tokens):
        raise ValueError('nonempty tokenizer words required')
    tagged=tuple(tag(list(tokens)))
    if (len(tagged)!=len(tokens)or any(len(item)!=2 or item[0]!=word
            or not isinstance(item[1],str)or not item[1]for word,item in zip(tokens,tagged,strict=True))):
        raise ValueError('one aligned grammatical tag per token required')
    actions=tuple(word for word,kind in tagged if kind in VERBS and word.casefold()not in AUXILIARIES)
    return QueryActions(tokens,actions)
