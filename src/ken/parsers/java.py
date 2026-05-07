"""Java symbol + import extractor (tree-sitter-java)."""

from __future__ import annotations

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from ken.parsers._helpers import child_text, doc_from_block_comment, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_LANG = Language(tsjava.language())
_PARSER = Parser(_LANG)


def parse_java_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope_name="", out=out)
    return out


def _walk(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "class_declaration":
            _emit_type(child, src, "class", scope_name, out)
        elif kind == "interface_declaration":
            _emit_type(child, src, "interface", scope_name, out)
        elif kind == "enum_declaration":
            _emit_type(child, src, "enum", scope_name, out)
        elif kind == "record_declaration":
            _emit_type(child, src, "record", scope_name, out)
        elif kind == "import_declaration":
            _emit_import(child, src, out)
        elif child.is_named:
            _walk(child, src, scope_name, out)


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
    if body is None:
        return
    for member in body.children:
        if member.type in ("method_declaration", "constructor_declaration"):
            mname = node_text(member.child_by_field_name("name"), src)
            if not mname:
                continue
            mkind = "constructor" if member.type == "constructor_declaration" else "method"
            out.symbols.append(
                ParsedSymbol(
                    kind=mkind,
                    name=mname,
                    qualname=f"{qual}.{mname}",
                    line_start=member.start_point[0] + 1,
                    line_end=member.end_point[0] + 1,
                    docstring=doc_from_block_comment(member, src),
                )
            )
        elif member.type in ("class_declaration", "interface_declaration", "enum_declaration"):
            # Recurse into nested types — Java's inner classes are common
            # enough that surfacing them is worth it.
            inner_kind = {
                "class_declaration": "class",
                "interface_declaration": "interface",
                "enum_declaration": "enum",
            }[member.type]
            _emit_type(member, src, inner_kind, qual, out)


def _emit_import(node: Node, src: bytes, out: ParsedFile) -> None:
    line = node.start_point[0] + 1
    # ``import com.foo.Bar;`` — the dotted path lives directly under the
    # import_declaration, with optional `static` and trailing `*`.
    text = node_text(node, src) or ""
    inner = text.removeprefix("import").strip().rstrip(";").strip()
    if inner.startswith("static"):
        inner = inner[len("static"):].strip()
    inner = inner.rstrip(".*").strip()
    if inner:
        out.imports.append(ParsedImport(module=inner, line=line))
