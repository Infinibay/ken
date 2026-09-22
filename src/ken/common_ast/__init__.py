"""Common source AST, independent of the KQL query-syntax AST."""
from .model import VERSION, Node, Scope, Symbol, Reference, Link, Program
from .normalize import normalize


def parse(source: str | bytes, language: str, path: str = 'snippet') -> Program:
    from ken.structural.frontend import lower_source
    return normalize(lower_source(source,language,path))


__all__=['VERSION','Node','Scope','Symbol','Reference','Link','Program','normalize','parse']
