"""Interpret explicit symbol requirements; observe source evidence separately."""
from __future__ import annotations
from collections.abc import Collection, Sequence
from dataclasses import dataclass
import re
from ken.retrieval.intent import _TEST_OBJECT, interpret
from ken.retrieval.model import EntityKey, SearchRequest
from ken.retrieval.piece_catalog import SourceCatalog

def requested_operations(query: str) -> set[str]:
    lower = query.casefold()
    required = set()
    if (re.search(r'\b(?:retain\w*|preserv\w*|keep\w*)\b', lower)
            and re.search(r'\bexception\b', lower) and re.search(r'\bcause\b', lower)
            and not re.search(r'\b(?:not|without|suppress\w*)\b[^.;]{0,60}\bcause\b', lower)):
        family = 'AttributeError' if re.search(r'\battribute[\s-]+error\b', lower) else '*'
        required.add('cause:' + family)
    if (re.search(r'\b(?:mapping|dictionary)\b', lower) and re.search(r'\bkey\b', lower)
            and re.search(r'\b(?:assign\w*|writ\w*|set\w*)\b', lower)
            and re.search(r'\b(?:remember\w*|previous|old|undo|absent)\b', lower)
            and not re.search(r'\b(?:without|never|not)\s+(?:assign\w*|writ\w*|set\w*)\b', lower)):
        required.add('snapshot_keyed_write')
    if (re.search(r'\breturn\w*\b', lower) and re.search(r'\b(?:flag|boolean|state)\b', lower)
            and re.search(r'\bor\b', lower) and re.search(r'\b(?:updat\w*|refresh\w*|assign\w*)\b', lower)
            and not re.search(r'\b(?:without|never|not)\s+(?:updat\w*|refresh\w*|assign\w*)\b', lower)):
        required.add('returned_flag_refresh')
    return required


def prefer_operations(required: Collection[str], witnesses: Sequence[Collection[str]],
                      order: Sequence[int]) -> list[int]:
    def matches(observed: Collection[str]) -> bool:
        return all((any(item.startswith('cause:') for item in observed) if item == 'cause:*'
                    else item in observed) for item in required)
    return sorted(order, key=lambda index: not matches(witnesses[index])) if required else list(order)


_SUPPORT = re.compile(r'^\s+(?:helpers?|fixtures?|factor(?:y|ies)|builders?|utilit(?:y|ies))\b')
_JAVA_TEST = re.compile(r'(?m)^\s*@(?:[\w]+\.)*(?:Test|RepeatedTest|ParameterizedTest|TestFactory|TestTemplate)\b')


def requests_test_case(request: SearchRequest) -> bool:
    query = request.query
    if interpret(request).purpose != 'tests':
        return False
    lower = query.casefold().strip()
    subject = re.sub(r'^where\s+(?:does|do|is|are)\s+', 'find ', lower)
    if re.search(r'\b[\w]+-double\s+(?:factory|helper|fixture|builder)\b', subject):
        return False
    match = _TEST_OBJECT.match(subject)
    if match:
        return not bool(_SUPPORT.match(subject[match.end():]))
    return bool(re.match(r'^where\s+(?:is|are)\b', lower) and re.search(r'\btested\b', lower))


def is_test_case(key: EntityKey, catalog: SourceCatalog) -> bool:
    if (key.kind not in {'function', 'method'} or key not in catalog.owners
            or catalog.owners[key][0].role != 'test' or catalog.enclosing_callable(key) is not None):
        return False
    name = (key.qualname or '').rsplit('.', 1)[-1]
    if key.path.endswith(('.py', '.pyi')):
        return name.startswith('test')
    if key.path.endswith('.java'):
        start, end = catalog.extent(key)
        declaration = '\n'.join(catalog.lines[key.path][start-1:min(end, start+11)]).split('{', 1)[0]
        return bool(_JAVA_TEST.search(declaration))
    return False


_OPERATORS = frozenset({'and', 'or', 'not', 'in', 'is'})
_WORDS = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')


def explicit_code_terms(query: str) -> frozenset[str]:
    words = {word.casefold() for word in _WORDS.findall(query) if word.isupper()}
    words.update(match.group(1).casefold() for match in re.finditer(r'`([A-Za-z]+)`', query))
    operators = words & _OPERATORS
    if re.search(r'\bbit[\s-]?wise\b', query, re.IGNORECASE):
        # The keyword witness understands boolean syntax, not bitwise semantics.
        # Do not turn a named bitwise operation into a hard boolean preference.
        operators -= {'and', 'or', 'not'}
    return frozenset(operators)


def prefer_explicit_code_terms(query: str, implementations: Sequence[str], order: Sequence[int]) -> list[int]:
    if sorted(order) != list(range(len(implementations))):
        raise ValueError('candidate order must be a permutation')
    required = explicit_code_terms(query)
    if not required:
        return list(order)
    present = [{word.casefold() for word in _WORDS.findall(text)}
               | ({'and'} if '&&' in text else set())
               | ({'or'} if '||' in text else set()) for text in implementations]
    return sorted(order, key=lambda index: not required <= present[index])


@dataclass(frozen=True)
class SymbolRequirements:
    operations: frozenset[str]
    operators: frozenset[str]
    test_case: bool


def requirements(request: SearchRequest) -> SymbolRequirements:
    return SymbolRequirements(frozenset(requested_operations(request.query)),
                              explicit_code_terms(request.query), requests_test_case(request))
