"""The static builtin exception types a handler header can identify."""
import ast
import builtins
from collections.abc import Mapping, Sequence

from .model import IR, Operation


def shadowed_bindings(graph: IR) -> dict[str, set[str]]:
    """Declarations and imports shadow builtins without binding-reference facts."""
    result: dict[str, set[str]] = {}
    for fact in graph.facts:
        if fact.relation in {'DECLARES', 'HAS_PARAMETER'}:
            entity = graph.entities.get(fact.object)
            if entity is not None:
                result.setdefault(fact.subject, set()).add(entity.name)
        if fact.relation != 'IMPORT_SYNTAX' or fact.attrs.get('language') != 'python':
            continue
        names = result.setdefault(fact.subject, set())
        try:
            statement = ast.parse(fact.object).body[0]
        except (SyntaxError, IndexError):
            names.add('*')
            continue
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or (alias.name.split('.')[0] if isinstance(statement, ast.Import)
                                         else alias.name) for alias in statement.names)
    return result


def handler_types(arm: Operation, children: Mapping[str, Sequence[Operation]],
                  bound_references: set[str], shadowed: set[str]) -> tuple[str, ...] | None:
    todo = [c for c in children.get(arm.id, ()) if c.role == 'value' or c.native_kind == 'as_pattern']
    if not todo:
        return ('BaseException',)
    names: set[str] = set()
    while todo:
        node = todo.pop()
        if node.role == 'alias':
            continue
        if node.native_kind == 'identifier':
            name = node.attrs.get('text', '')
            value = getattr(builtins, name, None)
            if (node.id in bound_references or name in shadowed or '*' in shadowed
                    or not isinstance(value, type) or not issubclass(value, BaseException)):
                return None
            names.add(name)
        elif node.native_kind not in {'tuple', 'as_pattern', 'parenthesized_expression'}:
            return None
        todo.extend(children.get(node.id, ()))
    return tuple(sorted(names)) or None


def consumes(earlier: Sequence[str], later: Sequence[str]) -> bool:
    """Whether selected builtin headers have consumed every later subtype."""
    return bool(later) and all(any(issubclass(getattr(builtins, child), getattr(builtins, parent))
                                  for parent in earlier) for child in later)


def catches_close(types: tuple[str, ...] | None) -> str:
    if types is None:
        return 'unknown'
    return 'yes' if consumes(types, ('GeneratorExit',)) else 'no'
