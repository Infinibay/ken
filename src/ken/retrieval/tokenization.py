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


def code_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORDS.findall(unicodedata.normalize("NFKC", text)):
        # Bound both retained entries and identifier size. Return a fresh list
        # so callers cannot mutate the shared lexical decomposition.
        tokens.extend(_identifier_tokens(raw) if len(raw) <= 256 else _split_identifier(raw))
    return tokens
