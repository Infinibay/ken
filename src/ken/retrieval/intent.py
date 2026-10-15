"""Interpret explicit search instructions; behavior content remains model evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ken.retrieval.model import SearchRequest
from ken.search import _identifier_query


_TEST_OBJECT = re.compile(
    r"^¿?(?:which|what|find|show|locate|qué|que|cuál|busca|buscá|muestra|encuentra)\s+"
    r"(?P<modifiers>(?:[\w-]+\s+){0,8}?)(?:tests?|pruebas?)\b")
_OBJECT_BOUNDARIES = frozenset((
    "function method class module file symbol implementation handler helper "
    "función funcion método metodo clase módulo modulo archivo implementación "
    "that which where who when whose que "
    "in of for from with to en de con para por"
).split())
_DECLARATION_KINDS = 'class|struct|interface|enum|trait|type|function|method|utility|helper|clase|tipo|iterador|iterator'
_NATIVE_MODIFIERS = 'public|private|protected|abstract|sealed|final|static|async'
_NAMED_DECLARATION = (
    re.compile(r'^(?:show|find|locate)\s+(?:the\s+)?'
        rf'(?:(?:{_NATIVE_MODIFIERS})\s+)*(?P<name>`?[\w$]+(?:[.:]+[\w$]+)*`?)\s+'
        r'(?:(?!(?:that|which|where|for|and|or)\b)[\w-]+\s+){0,2}'
        rf'(?P<kind>{_DECLARATION_KINDS})\s+(?:definition|declaration)\b', re.I),
    re.compile(r'\b(?:definición|declaración)\s+(?:de\s+la\s+|del\s+|de\s+)?'
        rf'(?P<kind>{_DECLARATION_KINDS})\s+(?P<name>`?[\w$]+(?:[.:]+[\w$]+)*`?)',re.I),
)
_NAMED_OBJECT = (
    re.compile(r'^(?:show|find|locate)\s+(?:the\s+)?'
        rf'(?:(?:{_NATIVE_MODIFIERS})\s+)*(?P<name>`?[\w$]+(?:[.:]+[\w$]+)*`?)\s+'
        rf'(?:[\w]+-[\w-]+\s+){{0,2}}(?P<kind>{_DECLARATION_KINDS})[.!?]*$',re.I),
    re.compile(r'^(?:mostrame|muestra|busca|buscá|encuentra)\s+(?:(?:el|la)\s+)?'
        rf'(?P<kind>{_DECLARATION_KINDS})\s+(?P<name>`?[\w$]+(?:[.:]+[\w$]+)*`?)'
        r'(?=\s+(?:para|que)\b|[.!?]*$)',re.I),
)


def _named_declaration(query: str) -> tuple[str, str | None] | None:
    for pattern in (*_NAMED_DECLARATION, *_NAMED_OBJECT):
        match = pattern.search(query)
        if match is None or re.search(r'\b(?:and|or|y|o)\b',query[match.end():],re.I):
            continue
        name = _identifier_query(match['name'].strip('`'))
        if name is None or name.casefold() in _OBJECT_BOUNDARIES:
            continue
        # Without an explicit declaration noun, descriptive prose needs a
        # visible code identifier (quoted, qualified, snake_case or capitals).
        if pattern in _NAMED_OBJECT and not (match['name'].startswith('`')
                or not name.islower() or any(c in name for c in '_.:')):
            continue
        kind = match['kind'].casefold()
        concrete = {'clase':'class', 'class':'class', 'struct':'struct', 'interface':'interface',
                    'enum':'enum','trait':'trait'}.get(kind)
        return name,concrete
    return None


def _requests_test_source(query: str) -> bool:
    """Recognize the requested noun, including modifiers, before a clause boundary."""
    match = _TEST_OBJECT.match(query)
    return bool(match and not (_OBJECT_BOUNDARIES & set(match['modifiers'].split())))


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
        if _requests_test_source(lower):
            purpose = "tests"
        elif re.search(r"\b(?:example|ejemplo)\b", lower):
            purpose = "usage"
        else:
            purpose = "implementation"
    raw = _identifier_query(query)
    explicit = bool(re.search(r"\b(?:definition|declaration|definición|declaración|defined|declared|"
                              r"defines|declares|definid[oa]|declarad[oa]|declara)\b", lower)
                    or (re.search(r"^(?:show|find|locate|mostrame|muestra|busca|buscá|encuentra)\b", lower)
                        and re.search(rf"\b(?:{_DECLARATION_KINDS}|función|método)\b", lower)))
    if raw is not None:
        return QueryIntent(purpose, False, (raw,))
    if not explicit:
        return QueryIntent(purpose)
    quoted = tuple(identifier for text in re.findall(r"`([^`]+)`", query)
                   if (identifier := _identifier_query(text)) is not None)
    named = _named_declaration(query) if len(quoted) <= 1 else None
    if named is not None:
        return QueryIntent(purpose,True,(named[0],),named[1])
    stop = {"show", "find", "locate", "mostrame", "muestra", "busca", "the", "a", "an", "la", "el",
            "de", "del", "of", "definition", "declaration", "definición", "declaración", "class", "clase",
            "function", "función", "method", "método", "helper", "utility",
            "where", "is", "defined", "declared", "defines", "declares", "dónde", "donde",
            "está", "esta", "definido", "definida", "declarado", "declarada", "declara", "qué", "que",
            "archivo", "fuente", "source", "file"}
    identifiers = quoted or tuple(token for token in re.findall(r"[\w$]+(?:[.:]+[\w$]+)*", query)
                        if token.casefold() not in stop)
    # An instruction to find a function can still describe behavior. Treating
    # every remaining prose word as a name grants an accidental symbol match
    # authority to bypass retrieval. Only an unambiguous named target does so.
    if len(identifiers) != 1:
        return QueryIntent(purpose)
    kind = "class" if re.search(r"\b(?:class|clase)\b", lower) else None
    return QueryIntent(purpose, True, identifiers, kind)
