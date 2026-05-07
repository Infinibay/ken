"""TypeScript parser: interface / type / function / class / arrow / TSX."""

from __future__ import annotations


def test_extracts_interface(parse_ts):
    src = '''interface User {
    id: number;
    name: string;
}
'''
    out = parse_ts(src)
    syms = [s for s in out.symbols if s.kind == "interface"]
    assert len(syms) == 1
    assert syms[0].name == "User"


def test_extracts_typed_function_with_jsdoc(parse_ts):
    src = '''/**
 * Add two numbers.
 */
function add(a: number, b: number): number {
    return a + b;
}
'''
    out = parse_ts(src)
    assert len(out.symbols) == 1
    s = out.symbols[0]
    assert s.name == "add"
    assert s.docstring == "Add two numbers."


def test_extracts_export_class_unwrapping(parse_ts):
    """`export class Foo` is wrapped in `export_statement` — the parser
    must walk through it to find the class."""
    src = '''/** Wraps an export. */
export class Wrapped {
    method() {}
}
'''
    out = parse_ts(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert "Wrapped" in by_qual
    # The JSDoc lives outside the export wrapper.
    assert by_qual["Wrapped"].docstring == "Wraps an export."
    assert "Wrapped.method" in by_qual


def test_extracts_type_alias_and_enum(parse_ts):
    src = '''type Id = string | number;
enum Status { Active, Inactive }
'''
    out = parse_ts(src)
    by_kind = {s.kind: s.name for s in out.symbols}
    assert by_kind.get("type") == "Id"
    assert by_kind.get("enum") == "Status"
