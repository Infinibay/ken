"""PowerShell symbol + import extractor.

The PowerShell grammar ships inside ``tree-sitter-language-pack`` (no
standalone wheel), so we pull the ``Language`` from there — same as Dart.

Grammar shape worth knowing (verified against tree-sitter-powershell):

* ``function_statement`` covers both ``function`` and ``filter`` (the leading
  keyword is an anonymous child). The name is a ``function_name`` child.
* ``class_statement`` / ``enum_statement`` carry the type name as their first
  ``simple_name`` child. Methods are ``class_method_definition`` nodes whose
  *direct* ``simple_name`` child is the method name (the return-type's name,
  if any, is nested under a ``type_literal`` and therefore not a direct child).
* PowerShell has no dedicated import grammar nodes. ``Import-Module``,
  ``using module``, and dot-sourcing (``. .\\foo.ps1``) all parse as ordinary
  ``command`` nodes, so imports are recovered by inspecting commands.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule), so it
# goes straight into Parser.
_PARSER = Parser(get_language("powershell"))

# Cmdlets that pull in another file/module worth recording as an import edge.
_IMPORT_CMDLETS = {"import-module", "ipmo"}
# Argument tokens we skip when hunting for a command's positional module arg.
_SKIP_ELEMENT_TYPES = {"command_argument_sep", "command_parameter"}


def parse_powershell_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_statement":
            _emit_function(child, src, scope, out)
        elif kind == "class_statement":
            _emit_class(child, src, scope, out)
        elif kind == "enum_statement":
            _emit_enum(child, src, scope, out)
        elif kind == "command":
            _emit_command(child, src, out)
        elif child.is_named:
            _walk(child, src, scope, out)


# ---- symbols --------------------------------------------------------------


def _emit_function(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    """``function Get-Thing { }`` and ``filter Foo { }`` (same node type)."""
    name_node = next(
        (c for c in node.named_children if c.type == "function_name"), None
    )
    name = node_text(name_node, src)
    if not name:
        return
    is_filter = any(c.type == "filter" for c in node.children)
    out.symbols.append(
        ParsedSymbol(
            kind="filter" if is_filter else ("method" if scope else "function"),
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_ps_doc(node, src),
        )
    )


def _emit_class(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = _first_simple_name(node, src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind="class",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_ps_doc(node, src),
        )
    )
    for member in node.named_children:
        if member.type == "class_method_definition":
            _emit_method(member, src, qual, out)


def _emit_method(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    """A method/constructor; the name is the *direct* ``simple_name`` child.

    A return-type literal (``[string] Speak()``) keeps its own name nested
    under ``type_literal``, so only the bare direct child is the method name.
    """
    name = _first_simple_name(node, src)
    if not name:
        return
    # The constructor shares its name with the enclosing class.
    cls = scope.rsplit(".", 1)[-1]
    out.symbols.append(
        ParsedSymbol(
            kind="constructor" if name == cls else "method",
            name=name,
            qualname=f"{scope}.{name}",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_ps_doc(node, src),
        )
    )


def _emit_enum(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = _first_simple_name(node, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="enum",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_ps_doc(node, src),
        )
    )


# ---- imports --------------------------------------------------------------


def _emit_command(node: Node, src: bytes, out: ParsedFile) -> None:
    """Recover import edges from the three command-shaped PowerShell forms.

    * ``Import-Module <name|path>`` / ``ipmo ...``
    * ``using module <path>`` (``using namespace``/``assembly`` are skipped —
      they reference .NET types, not source files)
    * dot-sourcing ``. <path>`` (the ``.`` call operator runs a script in the
      current scope; ``&`` invocation is *not* an import and is ignored)
    """
    line = node.start_point[0] + 1

    # Dot-sourcing: a command_invokation_operator whose text is ".".
    inv = next(
        (c for c in node.children if c.type == "command_invokation_operator"), None
    )
    if inv is not None:
        if (node_text(inv, src) or "").strip() != ".":
            return
        expr = next(
            (c for c in node.named_children if c.type == "command_name_expr"), None
        )
        module = _clean_module(node_text(expr, src))
        if module:
            out.imports.append(ParsedImport(module=module, line=line))
        return

    name_node = next(
        (c for c in node.named_children if c.type == "command_name"), None
    )
    cmd = (node_text(name_node, src) or "").strip().lower()
    args = _positional_args(node, src)

    if cmd in _IMPORT_CMDLETS:
        if args:
            module = _clean_module(args[0])
            if module:
                out.imports.append(ParsedImport(module=module, line=line))
    elif cmd == "using" and len(args) >= 2 and args[0].lower() == "module":
        module = _clean_module(args[1])
        if module:
            out.imports.append(ParsedImport(module=module, line=line))


def _positional_args(node: Node, src: bytes) -> list[str]:
    """Text of a command's positional argument tokens (separators/`-Params`
    dropped) so ``Import-Module -Name Foo`` still yields ``Foo``.
    """
    elements = next(
        (c for c in node.named_children if c.type == "command_elements"), None
    )
    if elements is None:
        return []
    out: list[str] = []
    for c in elements.named_children:
        if c.type in _SKIP_ELEMENT_TYPES:
            continue
        text = node_text(c, src)
        if text:
            out.append(text)
    return out


def _clean_module(raw: str | None) -> str | None:
    """Normalise a module/path token into something the resolver can match.

    Strips surrounding quotes, turns Windows ``\\`` separators into ``/``, and
    rewrites the ``$PSScriptRoot`` prefix (the importing script's own
    directory) into a ``./`` relative path so dot-sourced siblings resolve.
    """
    if not raw:
        return None
    m = raw.strip().strip("'\"").strip()
    if not m:
        return None
    m = m.replace("\\", "/")
    for prefix in ("$PSScriptRoot/", "${PSScriptRoot}/", "$PSCommandPath/"):
        if m.startswith(prefix):
            m = "./" + m[len(prefix):]
            break
    return m or None


# ---- small grammar-specific helpers ---------------------------------------


def _first_simple_name(node: Node, src: bytes) -> str | None:
    """First *direct* ``simple_name`` child (type/method/enum name)."""
    for c in node.named_children:
        if c.type == "simple_name":
            return node_text(c, src)
    return None


def _ps_doc(node: Node, src: bytes) -> str | None:
    """First meaningful line of a preceding ``comment`` sibling.

    Handles single-line ``# ...`` comments and ``<# ... #>`` block / comment-
    based help, skipping ``.SYNOPSIS``-style help keyword lines.
    """
    sib = node.prev_named_sibling
    if sib is None or sib.type != "comment":
        return None
    text = node_text(sib, src) or ""
    text = text.removeprefix("<#").removesuffix("#>")
    for raw in text.splitlines():
        line = raw.strip().lstrip("#").strip()
        if not line or line.startswith("."):  # help keywords: .SYNOPSIS, etc.
            continue
        return line
    return None
