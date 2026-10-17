"""C++ symbol + include extractor (tree-sitter-cpp via language-pack).

The C++ grammar ships inside ``tree-sitter-language-pack`` (grammar name
``cpp``), same as Dart, so we take the ``Language`` from there — no new wheel.

Grammar shape worth knowing:

* A function's name lives at the bottom of a declarator chain: the outer
  ``declarator`` field may be a ``pointer_declarator`` / ``reference_declarator``
  (for ``int* f()`` / ``T& g()``), wrapping a ``function_declarator`` whose own
  ``declarator`` field is the actual name node — an ``identifier`` (free fn),
  ``field_identifier`` (in-class member), ``qualified_identifier``
  (``Foo::bar`` out-of-line def), ``destructor_name`` (``~Foo``) or
  ``operator_name``.
* In-class members appear as ``field_declaration`` (prototype), inline
  ``function_definition`` (body), or ``declaration`` (ctor/dtor prototypes).
  A ``declaration``/``field_declaration`` is only a callable when its innermost
  declarator is a ``function_declarator``; otherwise it is a data field and we
  skip it (consistent with other parsers not emitting struct fields).
* ``namespace_definition`` and ``extern "C"`` (``linkage_specification``) are
  transparent scopes; ``template_declaration`` transparently wraps the real
  declaration but owns the preceding doc comment.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import doc_from_block_comment, doc_from_line_comments, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol
from ken.parsers.scopes import scope_for_node

_PARSER = Parser(get_language("cpp"))

_TYPE_SPECIFIERS = {
    "class_specifier": "class",
    "struct_specifier": "struct",
    "union_specifier": "union",
}
_CONDITIONALS = frozenset({
    "preproc_if", "preproc_ifdef", "preproc_else", "preproc_elif", "preproc_elifdef",
})
_DECLARATOR_WRAPPERS = {
    "pointer_declarator",
    "reference_declarator",
    "parenthesized_declarator",
}


_CPP_SYNTAX = frozenset({
    "class_specifier", "namespace_definition", "namespace_alias_definition",
    "template_declaration", "alias_declaration", "using_declaration",
    "friend_declaration", "access_specifier", "reference_declarator",
    "qualified_identifier", "scoped_type_identifier", "lambda_expression",
    "new_expression", "delete_expression",
})


def has_cpp_syntax(source: bytes) -> bool:
    """Resolve ambiguous headers from syntax, excluding comments and literals."""
    pending = [_PARSER.parse(source).root_node]
    while pending:
        node = pending.pop()
        if node.type in _CPP_SYNTAX:
            return True
        pending.extend(node.named_children)
    return False


@dataclass(frozen=True)
class _Scope:
    """Lexical owner and enclosing namespace are distinct for local/friend code."""
    qualname: str = ""
    namespace: str = ""
    in_type: bool = False

    def qualify(self, name: str) -> str:
        return f"{self.qualname}.{name}" if self.qualname and name else (name or self.qualname)


def _record_symbol(out: ParsedFile, src: bytes, anchor: Node, symbol: ParsedSymbol, *,
                   body: Node | None = None) -> None:
    """Publish identity and its complete source contract together."""
    out.symbols.append(symbol)
    out.scopes.append(scope_for_node(src, anchor, symbol, body=body))


def parse_cpp_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, _Scope(), out)
    return out


def _walk(node: Node, src: bytes, scope: _Scope, out: ParsedFile) -> None:
    for child in node.children:
        _dispatch(child, src, scope, out)


def _dispatch(
    child: Node, src: bytes, scope: _Scope, out: ParsedFile
) -> None:
    kind = child.type
    if kind in _CONDITIONALS:
        # Index every source branch without guessing the caller's build flags.
        _walk(child, src, scope, out)
    elif kind == "preproc_include":
        _emit_include(child, src, out)
    elif kind == "function_definition":
        _emit_function(child, src, scope, out, doc_node=child)
    elif kind in ("declaration", "field_declaration"):
        _emit_callable_declaration(child, src, scope, out, doc_node=child)
    elif kind in _TYPE_SPECIFIERS:
        _emit_type(child, src, _TYPE_SPECIFIERS[kind], scope, out, doc_node=child)
    elif kind == "enum_specifier":
        _emit_enum(child, src, scope, out, doc_node=child)
    elif kind == "namespace_definition":
        name = _namespace_name(child, src)
        qualified = scope.qualify(name)
        new_scope = _Scope(qualified, qualified)
        body = child.child_by_field_name("body")
        if body is not None:
            _walk(body, src, new_scope, out)
    elif kind == "friend_declaration":
        _walk(child, src, _Scope(scope.namespace, scope.namespace), out)
    elif kind == "template_declaration":
        _emit_template(child, src, scope, out)
    elif kind == "linkage_specification":  # extern "C" { ... }
        body = child.child_by_field_name("body")
        if body is not None:
            _walk(body, src, scope, out)
    elif kind in ("alias_declaration", "type_definition"):
        _emit_typedef(child, src, scope, out)


def _emit_template(
    node: Node, src: bytes, scope: _Scope, out: ParsedFile
) -> None:
    """``template <...> <decl>`` — unwrap and emit the inner declaration, but
    keep *node* as the doc anchor (the doc comment precedes the template)."""
    for child in node.children:
        kind = child.type
        if kind == "function_definition":
            _emit_function(child, src, scope, out, doc_node=node)
        elif kind in ("declaration", "field_declaration"):
            _emit_callable_declaration(child, src, scope, out, doc_node=node)
        elif kind in _TYPE_SPECIFIERS:
            _emit_type(child, src, _TYPE_SPECIFIERS[kind], scope, out, doc_node=node)
        else:
            _dispatch(child, src, scope, out)


def _emit_function(
    node: Node, src: bytes, scope: _Scope, out: ParsedFile, *, doc_node: Node
) -> None:
    info = _declarator_name(node.child_by_field_name("declarator"), src)
    if info is None:
        _recover_namespace(node, src, scope, out)
        return
    owner = _append_callable(node, src, scope, out, info, doc_node=doc_node)
    body = node.child_by_field_name("body")
    if body is not None:
        _walk_local_types(body, src, _Scope(owner.qualname or owner.name, scope.namespace), out)


def _walk_local_types(node: Node, src: bytes, scope: _Scope, out: ParsedFile) -> None:
    """Find local types while excluding callable-looking macro/control blocks."""
    if node.type in _TYPE_SPECIFIERS:
        _emit_type(node, src, _TYPE_SPECIFIERS[node.type], scope, out, doc_node=node)
    elif node.type not in {"function_definition", "lambda_expression"}:
        for child in node.named_children:
            _walk_local_types(child, src, scope, out)


def _recover_namespace(node: Node, src: bytes, scope: _Scope, out: ParsedFile) -> None:
    """A preceding macro can make the grammar mistake a namespace for a function.

    Reparse only its namespace header, then walk the original body so all source
    positions remain exact. Unknown macro expansions never become fake owners.
    """
    body = node.child_by_field_name("body")
    if body is None:
        return
    keyword = next((child for child in node.named_children
                    if child.start_byte < body.start_byte and node_text(child, src) == "namespace"), None)
    if keyword is None:
        return
    header = src[keyword.start_byte:body.start_byte] + b"{}"
    recovered = _PARSER.parse(header).root_node
    if recovered.has_error or len(recovered.named_children) != 1:
        return
    namespace = recovered.named_children[0]
    if namespace.type != "namespace_definition":
        return
    name = _namespace_name(namespace, header)
    qualified = scope.qualify(name)
    new_scope = _Scope(qualified, qualified)
    _walk(body, src, new_scope, out)


def _emit_callable_declaration(
    node: Node, src: bytes, scope: _Scope, out: ParsedFile, *, doc_node: Node
) -> None:
    """A ``declaration``/``field_declaration`` is a callable only when its
    innermost declarator is a ``function_declarator`` (a prototype, an
    out-of-line def's signature, or a constructor/destructor). Plain
    variable/field declarations are skipped."""
    declared_type = node.child_by_field_name("type")
    if declared_type is not None and declared_type.type in _TYPE_SPECIFIERS:
        _emit_type(declared_type, src, _TYPE_SPECIFIERS[declared_type.type], scope, out,
                   doc_node=doc_node)
    info = _declarator_name(node.child_by_field_name("declarator"), src)
    if info is None:
        return
    _append_callable(node, src, scope, out, info, doc_node=doc_node)


def _append_callable(
    node: Node,
    src: bytes,
    scope: _Scope,
    out: ParsedFile,
    info: tuple[str, str, str],
    *,
    doc_node: Node,
) -> ParsedSymbol:
    name, qualifier, name_kind = info
    # Out-of-line qualifier (``Foo::bar``) becomes part of the dotted scope.
    full_scope = scope.qualname
    if qualifier:
        full_scope = scope.qualify(qualifier)
    qual = f"{full_scope}.{name}" if full_scope else name
    # A callable is a member when it is lexically inside a type body OR carries
    # an out-of-line ``Foo::`` qualifier. Namespace scope alone keeps it a
    # free function.
    is_member = scope.in_type or bool(qualifier)
    member_scope = full_scope if qualifier else scope.qualname
    if name_kind == "destructor":
        kind = "destructor"
    elif is_member and member_scope and name == member_scope.rsplit(".", 1)[-1]:
        kind = "constructor"
    elif is_member:
        kind = "method"
    else:
        kind = "function"
    symbol = ParsedSymbol(
        kind=kind,
        name=name,
        qualname=qual,
        line_start=doc_node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        docstring=_cpp_doc(doc_node, src),
    )
    _record_symbol(out, src, doc_node, symbol, body=node.child_by_field_name("body"))
    return symbol


def _emit_type(
    node: Node, src: bytes, kind: str, scope: _Scope, out: ParsedFile, *, doc_node: Node
) -> None:
    name = node_text(node.child_by_field_name("name"), src)
    if not name:
        return
    qual = scope.qualify(name)
    _record_symbol(out, src, doc_node,
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=qual,
            line_start=doc_node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_cpp_doc(doc_node, src),
        ),
        body=node.child_by_field_name("body"),
    )
    body = node.child_by_field_name("body")
    if body is not None:
        for member in body.children:
            _dispatch(member, src, _Scope(qual, scope.namespace, in_type=True), out)


def _emit_enum(
    node: Node, src: bytes, scope: _Scope, out: ParsedFile, *, doc_node: Node
) -> None:
    name = node_text(node.child_by_field_name("name"), src)
    if not name:
        return
    _record_symbol(out, src, doc_node,
        ParsedSymbol(
            kind="enum",
            name=name,
            qualname=scope.qualify(name),
            line_start=doc_node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_cpp_doc(doc_node, src),
        ),
        body=node.child_by_field_name("body"),
    )


def _emit_typedef(node: Node, src: bytes, scope: _Scope, out: ParsedFile) -> None:
    if node.type == "alias_declaration":  # using X = ...;
        name = next(
            (node_text(c, src) for c in node.named_children if c.type == "type_identifier"),
            None,
        )
    else:  # type_definition: typedef ... X;
        name = node_text(node.child_by_field_name("declarator"), src)
    if not name:
        return
    _record_symbol(out, src, node,
        ParsedSymbol(
            kind="typedef",
            name=name,
            qualname=scope.qualify(name),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_cpp_doc(node, src),
        ),
        body=node.child_by_field_name("body"),
    )


def _emit_include(node: Node, src: bytes, out: ParsedFile) -> None:
    """``#include <vector>`` (system) or ``#include "foo.hpp"`` (quoted).

    The quote/bracket style is the only signal C++ gives for internal vs
    external, so we preserve it: quoted paths keep a leading ``"`` marker the
    resolver/classifier keys on, angle-bracket paths are bare."""
    line = node.start_point[0] + 1
    for child in node.named_children:
        if child.type == "system_lib_string":
            text = (node_text(child, src) or "").strip("<>").strip()
            if text:
                out.imports.append(ParsedImport(module=text, line=line))
            return
        if child.type == "string_literal":
            inner = next(
                (c for c in child.named_children if c.type == "string_content"), None
            )
            text = node_text(inner, src) if inner is not None else None
            if text:
                out.imports.append(ParsedImport(module=f'"{text}"', line=line))
            return


# ---- declarator / name helpers --------------------------------------------


def _declarator_name(decl: Node | None, src: bytes) -> tuple[str, str, str] | None:
    """Descend a declarator to the function name. Returns
    ``(name, qualifier, name_kind)`` or None if not a function declarator.

    *qualifier* is the ``Foo::Bar`` scope of an out-of-line definition (dotted,
    minus the final name); *name_kind* is ``"destructor"`` for ``~Foo`` else
    ``"plain"``.
    """
    node = decl
    while node is not None and node.type in _DECLARATOR_WRAPPERS:
        node = node.child_by_field_name("declarator")
    if node is None or node.type != "function_declarator":
        return None
    inner = node.child_by_field_name("declarator")
    if inner is None:
        return None
    return _split_name(inner, src)


def _split_name(node: Node, src: bytes) -> tuple[str, str, str] | None:
    t = node.type
    if t in ("identifier", "field_identifier"):
        return (node_text(node, src) or "", "", "plain")
    if t == "destructor_name":
        return (node_text(node, src) or "", "", "destructor")
    if t == "operator_name":
        return (node_text(node, src) or "", "", "plain")
    if t == "qualified_identifier":
        full = node_text(node, src) or ""
        parts = [p for p in full.split("::") if p]
        if not parts:
            return None
        name = parts[-1]
        qualifier = ".".join(parts[:-1])
        kind = "destructor" if name.startswith("~") else "plain"
        return (name, qualifier, kind)
    return None


def _namespace_name(node: Node, src: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return (node_text(name, src) or "").replace("::", ".")
    return ""


def _cpp_doc(node: Node, src: bytes) -> str | None:
    return doc_from_block_comment(node, src) or doc_from_line_comments(
        node, src, prefix="///"
    )
