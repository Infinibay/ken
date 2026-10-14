"""Symmetric code vocabulary: full identifiers, components, and ordinary words."""
from __future__ import annotations

import re
import unicodedata

from ken.nametokens import split_camel

TOKENIZER_VERSION = "code-fields-v1"
_WORDS = re.compile(r"[^\W_][\w]*(?:[.$/-][^\W_][\w]*)*", re.UNICODE)
_STOP = frozenset(("a an the is are it its be been being this that these those "
                  "where what which how does do did with from for to of in on at and or "
                  "el la los las un una unos unas de del al en con para por y o "
                  "que qué donde dónde cómo cual cuál se es son está estan").split())


def code_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORDS.findall(unicodedata.normalize("NFKC", text)):
        variants = {raw.casefold()}
        for part in re.split(r"[._$/-]", raw):
            variants.add(part.casefold())
            variants.update(p.casefold() for p in split_camel(part))
        tokens.extend(sorted(t for t in variants if t and t not in _STOP))
    return tokens
