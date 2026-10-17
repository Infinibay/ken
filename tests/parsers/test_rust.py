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


def test_trait_default_method_has_canonical_owner_and_scope(parse_rust):
    source = """trait DataSource {
    /// Read a ready item.
    fn poll(&self) -> bool {
        self.ready()
    }
    fn ready(&self) -> bool;
}
"""
    parsed = parse_rust(source)
    method = next((s for s in parsed.symbols if s.qualname == "DataSource.poll"), None)
    assert method is not None
    assert (method.kind, method.line_start, method.line_end) == ("method", 3, 5)
    scope = next(s for s in parsed.scopes if s.symbol == method)
    assert scope.owner == "DataSource"
    assert "Read a ready item." in scope.documentation
    assert scope.signature == "fn poll(&self) -> bool"
    assert scope.implementation_start_line == 4


def test_nested_function_is_a_callable_with_its_lexical_owner(parse_rust):
    parsed = parse_rust("""fn outer() {
    fn local(value: u32) -> u32 { value + 1 }
    local(1);
}
""")
    local = next((s for s in parsed.symbols if s.qualname == "outer.local"), None)
    assert local is not None
    assert (local.kind, local.line_start, local.line_end) == ("function", 2, 2)
    assert next(s for s in parsed.scopes if s.symbol == local).owner == "outer"


def test_local_function_in_impl_method_is_not_a_method(parse_rust):
    parsed = parse_rust("""struct Agent;
impl Agent {
    fn run(&self) {
        fn local() {}
        local();
    }
}
""")
    symbols = {s.qualname: s for s in parsed.symbols}
    assert "Agent.run.local" in symbols
    assert symbols["Agent.run"].kind == "method"
    assert symbols["Agent.run.local"].kind == "function"


def test_local_function_discovery_handles_deep_expressions(parse_rust):
    expression = " + ".join(["value"] * 1500)
    source = "fn total(value: i64) -> i64 {\n  fn local() -> i64 { 1 }\n  " + expression + "\n}\n"
    parsed = parse_rust(source)
    assert {symbol.qualname for symbol in parsed.symbols} == {"total", "total.local"}
