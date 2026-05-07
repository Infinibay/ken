"""Rust parser: fn / struct / enum / trait / impl methods + use imports."""

from __future__ import annotations


def test_extracts_function_and_doc_comments(parse_rust):
    src = '''/// Doc line one.
/// Doc line two.
fn hello() -> u32 { 0 }
'''
    out = parse_rust(src)
    assert len(out.symbols) == 1
    s = out.symbols[0]
    assert s.kind == "function"
    assert s.name == "hello"
    assert s.docstring == "Doc line one."


def test_extracts_struct_and_impl_methods(parse_rust):
    src = '''struct Server {
    port: u16,
}

impl Server {
    /// Start it up.
    fn start(&self) {}
    fn stop(&self) {}
}
'''
    out = parse_rust(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert "Server" in by_qual and by_qual["Server"].kind == "struct"
    assert "Server.start" in by_qual and by_qual["Server.start"].kind == "method"
    assert "Server.stop" in by_qual
    assert by_qual["Server.start"].docstring == "Start it up."


def test_extracts_enum_and_trait(parse_rust):
    src = '''enum Color { Red, Blue }
trait Drawable { fn draw(&self); }
'''
    out = parse_rust(src)
    by_kind = {s.kind: s.name for s in out.symbols}
    assert by_kind.get("enum") == "Color"
    assert by_kind.get("trait") == "Drawable"


def test_extracts_use_imports(parse_rust):
    src = '''use std::collections::HashMap;
use serde::{Serialize, Deserialize};
'''
    out = parse_rust(src)
    modules = [imp.module for imp in out.imports]
    # First import passes through, the grouped one should be recorded with its prefix.
    assert any("std::collections::HashMap" in m for m in modules)
    assert any("serde" in m for m in modules)
