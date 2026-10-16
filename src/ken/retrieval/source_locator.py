"""Explicit namespace::qualified-symbol identity, separate from behavior prose."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ken.retrieval.model import EntityKey
from ken.retrieval.piece_catalog import module_name


_LOCATOR = re.compile(r'(?P<namespace>[\w$][\w$./-]*)::(?P<qualname>[\w$]+(?:\.[\w$]+)*)')
_LOOKUP = re.compile(
    r'^(?:locate|find|show|open|busca|buscá|localiza|muestra|mostrame)\s+'
    r'(?:(?:the\s+)?(?:definition|declaration)\s+of\s+|'
    r'(?:la\s+)?(?:definición|declaración)\s+(?:de|del)\s+)?', re.I)


@dataclass(frozen=True)
class SymbolLocator:
    """Bind a complete qualified symbol to a module or physical namespace."""

    namespace: str
    qualname: str

    def matches(self, key: EntityKey) -> bool:
        if key.qualname != self.qualname:
            return False
        if key.path == self.namespace or module_name(key.path) == self.namespace:
            return True
        path = PurePosixPath(key.path)
        # Java's source locator names the package directory. Indexing does not
        # store package declarations, so this asserts physical identity only.
        if path.suffix == '.java' and all(p.isidentifier() for p in self.namespace.split('.')):
            package = tuple(self.namespace.split('.'))
            return path.parent.parts[-len(package):] == package
        return False


def symbol_locator(query: str) -> SymbolLocator | None:
    """Recognize one complete lookup; references inside prose gain no authority."""
    text = _LOOKUP.sub('', query.strip(), count=1).rstrip('.?!').strip()
    if text.startswith('`') and text.endswith('`'):
        text = text[1:-1]
    match = _LOCATOR.fullmatch(text)
    if match is None:
        return None
    namespace = match['namespace']
    if any(part in {'', '.', '..'} for part in namespace.split('/')):
        return None
    if '..' in namespace or namespace.endswith('.'):
        return None
    if not all(part.replace('$', '_').isidentifier() for part in match['qualname'].split('.')):
        return None
    return SymbolLocator(namespace, match['qualname'])
