"""Remove explicit request frames without reducing behavioral constraints."""
from __future__ import annotations

import re

_EN_NOUN = r'function|method|class|module|file|helper|routine|implementation|code|test'
_ES_NOUN = r'función|funcion|método|metodo|clase|módulo|modulo|archivo|implementación|implementacion|código|codigo|prueba'
_EN_OBJECT = rf'(?:(?:the|a|an)\s+)?(?:{_EN_NOUN})\s+(?:(?:that|which)\s+)?'
_ES_OBJECT = rf'(?:(?:el|la|un|una)\s+)?(?:{_ES_NOUN})\s+(?:que\s+)?'
_FRAMES = tuple(re.compile(r'^\s*¿?'+pattern+r'(?P<body>[\s\S]+)$', re.I) for pattern in (
    rf'(?:which|what)\s+(?:(?:is|are)\s+)?{_EN_OBJECT}',
    rf'(?:find|show|locate)\s+(?:me\s+)?{_EN_OBJECT}',
    rf'where\s+(?:is|are)\s+(?:{_EN_OBJECT})?',
    rf'(?:qué|que|cuál|cual)\s+(?:(?:es|son)\s+)?{_ES_OBJECT}',
    rf'(?:busca|buscá|muestra|mostrame|encuentra|localiza)\s+{_ES_OBJECT}',
    rf'(?:dónde|donde)\s+(?:está|esta|están|estan)\s+(?:{_ES_OBJECT})?',
))
_BARE_NOUNS = frozenset((*_EN_NOUN.split('|'), *_ES_NOUN.split('|')))


def content_query(query: str) -> str:
    """Keep the original query when the frame has no informative remainder."""
    for pattern in _FRAMES:
        if match := pattern.fullmatch(query):
            body = match['body'].strip()
            informative = body.strip('¿?!. ').casefold()
            informative = re.sub(r'^(?:the|a|an|el|la|un|una)\s+', '', informative)
            if informative and informative not in _BARE_NOUNS:
                return body
    return query
