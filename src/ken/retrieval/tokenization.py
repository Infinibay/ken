"""Symmetric code vocabulary: full identifiers, components, and ordinary words."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from ken.nametokens import split_camel

TOKENIZER_VERSION = "code-fields-v1"
_WORDS = re.compile(r"[^\W_][\w]*(?:[.$/-][^\W_][\w]*)*", re.UNICODE)
_COMPONENTS = re.compile(r"[._$/-]")
_STOP = frozenset(("a an the is are it its be been being this that these those "
                  "where what which how does do did with from for to of in on at and or "
                  "el la los las un una unos unas de del al en con para por y o "
                  "que qué donde dónde cómo cual cuál se es son está estan").split())


def _split_identifier(raw: str) -> tuple[str, ...]:
    variants = {raw.casefold()}
    for part in _COMPONENTS.split(raw):
        variants.add(part.casefold())
        variants.update(p.casefold() for p in split_camel(part))
    return tuple(sorted(t for t in variants if t and t not in _STOP))


@lru_cache(maxsize=16384)
def _identifier_tokens(raw: str) -> tuple[str, ...]:
    return _split_identifier(raw)


def _lexeme_tokens(raw: str) -> tuple[str, ...]:
    return _identifier_tokens(raw) if len(raw) <= 256 else _split_identifier(raw)


def code_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORDS.findall(unicodedata.normalize("NFKC", text)):
        # Bound both retained entries and identifier size. Return a fresh list
        # so callers cannot mutate the shared lexical decomposition.
        tokens.extend(_lexeme_tokens(raw))
    return tokens


def code_terms(text: str, *, limit: int | None = None) -> list[str]:
    """First distinct vocabulary terms, without materializing repeated occurrences."""
    if limit is not None and limit < 0:
        raise ValueError('term limit must be nonnegative')
    if limit == 0:
        return []
    seen_words: set[str] = set()
    seen_terms: set[str] = set()
    terms: list[str] = []
    for match in _WORDS.finditer(unicodedata.normalize('NFKC', text)):
        raw = match.group()
        if raw in seen_words:
            continue
        seen_words.add(raw)
        for term in _lexeme_tokens(raw):
            if term not in seen_terms:
                seen_terms.add(term)
                terms.append(term)
                if limit is not None and len(terms) == limit:
                    return terms
    return terms
