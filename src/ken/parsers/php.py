r"""PHP symbol + import extractor.

The PHP grammar ships inside ``tree-sitter-language-pack`` (no standalone
wheel needed), so we pull the ``Language`` from there — same approach as
``dart.py``.

Grammar shape worth knowing:

* Top-level declarations are ``class_declaration`` / ``interface_declaration``
  / ``trait_declaration`` / ``enum_declaration`` / ``function_definition``,
  each with a ``name`` field and a ``body`` ``declaration_list``.
* Class members are ``method_declaration`` (with a ``name`` field), plus
  ``property_declaration`` / ``const_declaration`` which we skip — only
  callables and types are worth a symbol.
* Imports come in two flavours: ``namespace_use_declaration`` (``use Foo\Bar;``,
  grouped ``use Foo\{A, B};`` and aliased ``use Foo\Bar as B;``) and the
  ``require``/``include`` family of expressions for file-path includes.
* Doc comments are ``/** */`` ``comment`` siblings, handled by the shared
  ``doc_from_block_comment`` helper.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import child_text, doc_from_block_comment, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_PARSER = Parser(get_language("php"))

# Top-level / nested type declarations -> ken kind.
_TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "enum_declaration": "enum",
}

# require / include expression nodes carrying a file path.
_INCLUDE_EXPRS = {
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
}


def parse_php_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind in _TYPE_KINDS:
            _emit_type(child, src, _TYPE_KINDS[kind], scope, out)
        elif kind == "function_definition":
            _emit_function(child, src, scope, out)
        elif kind == "namespace_use_declaration":
            _emit_use(child, src, out)
        elif kind in _INCLUDE_EXPRS:
            _emit_include(child, src, out)
        elif child.is_named:
            # Recurse through namespace blocks, expression_statement wrappers,
            # etc. so nested declarations / includes are still found.
            _walk(child, src, scope, out)


def _emit_type(node: Node, src: bytes, kind: str, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_block_comment(node, src),
        )
    )
    body = node.child_by_field_name("body")
    if body is not None:
        _emit_members(body, src, qual, out)


def _emit_members(body: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for member in body.named_children:
        if member.type == "method_declaration":
            name = child_text(member, "name", src)
            if not name:
                continue
            out.symbols.append(
                ParsedSymbol(
                    kind="method",
                    name=name,
                    qualname=f"{scope}.{name}",
                    line_start=member.start_point[0] + 1,
                    line_end=member.end_point[0] + 1,
                    docstring=doc_from_block_comment(member, src),
                )
            )


def _emit_function(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="function",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_block_comment(node, src),
        )
    )


def _emit_use(node: Node, src: bytes, out: ParsedFile) -> None:
    r"""Handle ``use Foo\Bar;``, ``use Foo\Bar as B;`` and grouped
    ``use Foo\{A, B};``. Each imported name becomes one ParsedImport whose
    module is the fully-qualified backslash name (alias dropped).
    """
    line = node.start_point[0] + 1
    # Grouped form: a ``namespace_name`` prefix + ``namespace_use_group`` body.
    prefix_node = None
    group_node = node.child_by_field_name("body")
    if group_node is None:
        group_node = next(
            (c for c in node.named_children if c.type == "namespace_use_group"), None
        )
    if group_node is not None:
        prefix_node = next(
            (c for c in node.named_children if c.type == "namespace_name"), None
        )
        prefix = (node_text(prefix_node, src) or "").rstrip("\\")
        for clause in group_node.named_children:
            if clause.type != "namespace_use_clause":
                continue
            tail = _clause_name(clause, src)
            if tail:
                mod = f"{prefix}\\{tail}" if prefix else tail
                out.imports.append(ParsedImport(module=mod, line=line))
        return
    # Simple / aliased form: one or more top-level ``namespace_use_clause``s.
    for clause in node.named_children:
        if clause.type != "namespace_use_clause":
            continue
        mod = _clause_name(clause, src)
        if mod:
            out.imports.append(ParsedImport(module=mod, line=line))


def _clause_name(clause: Node, src: bytes) -> str | None:
    """Module string of a ``namespace_use_clause``, excluding any ``as`` alias.

    The name is the first ``qualified_name`` / ``name`` / ``namespace_name``
    child; the ``alias`` lives in the ``alias`` field and is ignored.
    """
    alias = clause.child_by_field_name("alias")
    for c in clause.named_children:
        if c is alias:
            continue
        if c.type in ("qualified_name", "namespace_name", "name"):
            return (node_text(c, src) or "").strip()
    return None


def _emit_include(node: Node, src: bytes, out: ParsedFile) -> None:
    """``require_once 'helpers.php';`` — record the literal path only.

    Concatenated paths (``__DIR__ . '/x.php'``) are a ``binary_expression``
    with no single literal, so they are skipped.
    """
    string_node = next((c for c in node.named_children if c.type == "string"), None)
    if string_node is None:
        return
    content = next(
        (c for c in string_node.named_children if c.type == "string_content"), None
    )
    text = node_text(content, src) if content is not None else None
    if text:
        out.imports.append(ParsedImport(module=text, line=node.start_point[0] + 1))
