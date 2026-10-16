"""Observe local source relations without claiming interprocedural execution.

Unknown or unsupported syntax supplies no preference. Parsing is cached within
the authenticated source catalog and nested callable bodies remain separate.
"""
from __future__ import annotations
import ast
import re
from pathlib import Path
from collections.abc import Iterator, Sequence
from tree_sitter import Node
from ken.retrieval.model import EntityKey
from ken.retrieval.piece_catalog import SourceCatalog
from ken.structural.frontend import FUNCTIONS as _CALLABLE, LANGUAGES, parser_for


class _Syntax:
    def __init__(self, source: bytes, path: str):
        self.source = source
        self.tree = parser_for(LANGUAGES[Path(path).suffix], path).parse(source)

    def _raw(self, node: Node) -> str:
        return self.source[node.start_byte:node.end_byte].decode('utf8')


def _same(left: ast.AST, right: ast.AST) -> bool:
    return ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False)


def _direct_nodes(root: ast.AST) -> Iterator[ast.AST]:
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                pending.append(child)


def _snapshot_write(statements: Sequence[ast.stmt]) -> bool:
    for read, write, record in zip(statements, statements[1:], statements[2:]):
        if not (isinstance(read, ast.Assign) and len(read.targets) == 1 and isinstance(read.targets[0], ast.Name)
                and isinstance(read.value, ast.Call) and isinstance(read.value.func, ast.Attribute)
                and read.value.func.attr == 'get' and read.value.args):
            continue
        if not (isinstance(write, ast.Assign) and len(write.targets) == 1
                and isinstance(write.targets[0], ast.Subscript)):
            continue
        target = write.targets[0]
        if not (_same(target.value, read.value.func.value) and _same(target.slice, read.value.args[0])):
            continue
        if not (isinstance(record, ast.Expr) and isinstance(record.value, ast.Call)
                and isinstance(record.value.func, ast.Attribute) and record.value.func.attr == 'append'
                and len(record.value.args) == 1 and isinstance(record.value.args[0], (ast.Tuple, ast.List))):
            continue
        values = record.value.args[0].elts
        if (len(values) == 3 and _same(values[0], target.value) and _same(values[1], target.slice)
                and isinstance(values[2], ast.Name) and values[2].id == read.targets[0].id):
            return True
    return False


class OperationWitnesses:
    def __init__(self, catalog: SourceCatalog):
        self.catalog = catalog
        self._python_trees: dict[str, ast.Module | None] = {}
        self._syntax: dict[str, _Syntax] = {}
        self._cache: dict[EntityKey, frozenset[str]] = {}

    def for_owner(self, key: EntityKey) -> frozenset[str]:
        if key in self._cache:
            return self._cache[key]
        result: set[str] = set()
        if key.path.endswith(('.py', '.pyi')):
            root = self._python_node(key)
            if root is not None:
                for node in _direct_nodes(root):
                    if isinstance(node, ast.Raise) and node.cause is not None and not (
                            isinstance(node.cause, ast.Constant) and node.cause.value is None):
                        name = node.exc.func if isinstance(node.exc, ast.Call) else None
                        family = name.id if isinstance(name, ast.Name) else 'unknown'
                        result.add('cause:' + family)
                    for field in ('body', 'orelse', 'finalbody'):
                        block = getattr(node, field, None)
                        if isinstance(block, list) and _snapshot_write(block):
                            result.add('snapshot_keyed_write')
                    if isinstance(node, ast.Return) and isinstance(node.value, ast.BoolOp) and isinstance(node.value.op, ast.Or):
                        values = node.value.values
                        if (len(values) == 2 and isinstance(values[1], ast.NamedExpr)
                                and isinstance(values[0], ast.Name) and isinstance(values[1].target, ast.Name)
                                and values[0].id == values[1].target.id and isinstance(values[1].value, ast.Call)):
                            result.add('returned_flag_refresh')
        elif key.path.endswith(('.java', '.js', '.mjs', '.cjs', '.ts', '.tsx')):
            self._returned_update(key, result)
        self._cache[key] = frozenset(result)
        return self._cache[key]

    def _python_node(self, key: EntityKey) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None:
        if key.path not in self._python_trees:
            try:
                self._python_trees[key.path] = ast.parse('\n'.join(self.catalog.lines[key.path]))
            except (SyntaxError, ValueError):
                self._python_trees[key.path] = None
        tree = self._python_trees[key.path]
        if tree is None:
            return None
        start, end = self.catalog.extent(key)
        name = (key.qualname or '').rsplit('.', 1)[-1]
        matches = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                   and node.name == name and node.end_lineno == end and start <= node.lineno <= end]
        return matches[0] if len(matches) == 1 else None

    def _returned_update(self, key: EntityKey, result: set[str]) -> None:
        if key.path not in self._syntax:
            self._syntax[key.path] = _Syntax('\n'.join(self.catalog.lines[key.path]).encode('utf8'), key.path)
        syntax = self._syntax[key.path]
        start, end = self.catalog.extent(key)
        candidates = []
        pending = [syntax.tree.root_node]
        while pending:
            node = pending.pop()
            a, b = node.start_point[0]+1, node.end_point[0]+1
            if b < start or a > end:
                continue
            if node.type in _CALLABLE and start <= a <= b <= end:
                candidates.append(node)
            pending.extend(node.named_children)
        if not candidates:
            return
        root = min(candidates, key=lambda node: (node.start_byte, -node.end_byte))
        if root.end_point[0]+1 != end:
            return

        def unwrap(node: Node | None) -> Node | None:
            while node is not None and node.type == 'parenthesized_expression' and len(node.named_children) == 1:
                node = node.named_children[0]
            return node

        pending = [root]
        while pending:
            node = pending.pop()
            if node != root and node.type in _CALLABLE:
                continue
            if node.type == 'return_statement' and node.named_children:
                value = unwrap(node.named_children[0])
                if value is not None and value.type == 'binary_expression' and any(c.type == '||' for c in value.children):
                    left = unwrap(value.child_by_field_name('left'))
                    right = unwrap(value.child_by_field_name('right'))
                    if right is not None and right.type == 'assignment_expression':
                        target = unwrap(right.child_by_field_name('left'))
                        assigned = unwrap(right.child_by_field_name('right'))
                        if (left is not None and target is not None and assigned is not None
                                and assigned.type in {'call_expression', 'method_invocation'}
                                and re.sub(r'\s+', '', syntax._raw(left)) == re.sub(r'\s+', '', syntax._raw(target))):
                            result.add('returned_flag_refresh')
            pending.extend(node.named_children)
