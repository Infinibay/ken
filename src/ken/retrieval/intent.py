"""Interpret explicit search instructions; behavior content remains model evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ken.retrieval.model import SearchRequest
from ken.search import _identifier_query


@dataclass(frozen=True)
class QueryIntent:
    purpose: str
    identity: bool = False
    identifiers: tuple[str, ...] = ()
    kind: str | None = None


def interpret(request: SearchRequest) -> QueryIntent:
    query = request.query.strip()
    lower = query.casefold()
    purpose = request.purpose
    if purpose == "auto":
        if re.search(r"^(?:(?:which|what)\s+(?:unit\s+)?tests?\b|"
                     r"(?:find|show|locate)\s+(?:(?:the|a|an)\s+)?(?:unit\s+)?tests?\b|"
                     r"¿?(?:qué|que|cuál)\s+prueba\b|"
                     r"(?:busca|buscá|muestra|encuentra)\s+(?:(?:la|el|una|un)\s+)?(?:prueba|test)\b)", lower):
            purpose = "tests"
        elif re.search(r"\b(?:example|ejemplo)\b", lower):
            purpose = "usage"
        else:
            purpose = "implementation"
    raw = _identifier_query(query)
    explicit = bool(re.search(r"\b(?:definition|declaration|definición|declaración)\b", lower)
                    or (re.search(r"^(?:show|find|locate|mostrame|muestra|busca)\b", lower)
                        and re.search(r"\b(?:class|clase|function|función|method|método|helper|utility)\b", lower)))
    if raw is not None:
        return QueryIntent(purpose, False, (raw,))
    if not explicit:
        return QueryIntent(purpose)
    stop = {"show", "find", "locate", "mostrame", "muestra", "busca", "the", "a", "an", "la", "el",
            "de", "del", "definition", "declaration", "definición", "declaración", "class", "clase",
            "function", "función", "method", "método", "helper", "utility"}
    identifiers = tuple(token for token in re.findall(r"[\w$]+(?:[.:]+[\w$]+)*", query)
                        if token.casefold() not in stop)
    kind = "class" if re.search(r"\b(?:class|clase)\b", lower) else None
    return QueryIntent(purpose, True, identifiers, kind)
