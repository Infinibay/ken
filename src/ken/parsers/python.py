"""Python symbol + import extractor backed by tree-sitter.

What we pull out (and why):
  * top-level functions and classes (function-bodies via `function_definition`,
    classes via `class_definition`),
  * methods (function definitions nested inside a class body),
  * the **first line** of each docstring, which is what the embedder uses
    as the symbol's natural-language description (matches infinidev),
  * `import …` and `from … import …` modules.

Tree-sitter is fault-tolerant — even malformed Python parses, just with
ERROR nodes scattered around. We just walk and skip what doesn't match.
"""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# Module-level singleton — Parser objects are mutable but cheap to share.
# tree-sitter-python ships a pointer to the precompiled grammar.
_LANG = Language(tspython.language())
_PARSER = Parser(_LANG)


def parse_python_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    """Parse *source* and return the symbols / imports it defines."""
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope_name="", out=out)
    return out


def _walk(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_definition":
            _emit_function(child, src, scope_name, out)
            # Don't recurse into a function body — nested functions / classes
            # rarely surface as useful symbols (closures, decorators) and
            # they bloat the index. infinidev's parser does the same.
        elif kind == "class_definition":
            _emit_class(child, src, scope_name, out)
        elif kind in ("import_statement", "import_from_statement"):
            _emit_imports(child, src, out)
        else:
            _walk(child, src, scope_name, out)


def _emit_function(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    name = _child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope_name}.{name}" if scope_name else name
    sym_kind = "method" if scope_name else "function"
    out.symbols.append(
        ParsedSymbol(
            kind=sym_kind,
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_extract_docstring(node, src),
        )
    )


def _emit_class(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    name = _child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope_name}.{name}" if scope_name else name
    out.symbols.append(
        ParsedSymbol(
            kind="class",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_extract_docstring(node, src),
        )
    )
    body = node.child_by_field_name("body")
    if body is not None:
        _walk(body, src, scope_name=qual, out=out)


def _emit_imports(node: Node, src: bytes, out: ParsedFile) -> None:
    """Pull module names from both `import_statement` and `import_from_statement`.

    For ``import a.b, c`` we record two entries (one per name).  For
    ``from x.y import z`` we record `x.y`.  We deliberately don't unfold
    `z` — the symbol resolver handles names later when it links imports
    to symbol IDs.
    """
    line = node.start_point[0] + 1
    if node.type == "import_statement":
        for ch in node.children:
            mod = _module_name(ch, src)
            if mod:
                out.imports.append(ParsedImport(module=mod, line=line))
    elif node.type == "import_from_statement":
        # First "dotted_name" (or "relative_import") is the source module.
        for ch in node.children:
            if ch.type in ("dotted_name", "relative_import"):
                txt = _node_text(ch, src)
                if txt:
                    out.imports.append(ParsedImport(module=txt, line=line))
                break


def _module_name(node: Node, src: bytes) -> str | None:
    if node.type == "dotted_name":
        return _node_text(node, src)
    if node.type == "aliased_import":
        # form: <name> as <alias>
        for ch in node.children:
            if ch.type == "dotted_name":
                return _node_text(ch, src)
    return None


def _extract_docstring(node: Node, src: bytes) -> str | None:
    """Return the first line of the docstring, if the body opens with one.

    Python convention: a string-literal expression as the first statement
    of a function/class body *is* the docstring. We pull the literal,
    strip quotes, return the first non-empty line.
    """
    body = node.child_by_field_name("body")
    if body is None:
        return None
    # First child of `body` is `:`; the docstring is the next statement
    # if it's an `expression_statement` whose only child is a string.
    for stmt in body.children:
        if stmt.type != "expression_statement":
            if stmt.is_named:
                return None
            continue
        # First named child of the expression statement.
        for inner in stmt.children:
            if inner.type == "string":
                raw = _node_text(inner, src) or ""
                clean = raw.strip().strip("'\"").strip()
                first_line = next((ln.strip() for ln in clean.splitlines() if ln.strip()), "")
                return first_line or None
        return None
    return None


# --- tree-sitter helpers ----------------------------------------------------


def _child_text(node: Node, field: str, src: bytes) -> str | None:
    ch = node.child_by_field_name(field)
    return _node_text(ch, src) if ch is not None else None


def _node_text(node: Node | None, src: bytes) -> str | None:
    if node is None:
        return None
    try:
        return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover
        return None
