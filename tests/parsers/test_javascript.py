"""JavaScript parser: function decl / class+methods / arrow / imports."""

from __future__ import annotations


def test_extracts_function_declaration(parse_js):
    src = '''/**
 * Compute the answer.
 */
function compute(x) { return x + 1; }
'''
    out = parse_js(src)
    assert len(out.symbols) == 1
    s = out.symbols[0]
    assert s.name == "compute"
    assert s.kind == "function"
    assert s.docstring == "Compute the answer."


def test_extracts_class_with_methods(parse_js):
    src = '''class Box {
    /**
     * Open it.
     */
    open() {}
    close() {}
}
'''
    out = parse_js(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert "Box" in by_qual and by_qual["Box"].kind == "class"
    assert "Box.open" in by_qual and by_qual["Box.open"].docstring == "Open it."
    assert "Box.close" in by_qual


def test_extracts_arrow_function_assigned_to_const(parse_js):
    src = '''const handler = (req) => req.id;
'''
    out = parse_js(src)
    names = [s.name for s in out.symbols]
    assert "handler" in names


def test_extracts_import_module(parse_js):
    src = '''import { foo, bar } from "./utils.js";
import React from "react";
'''
    out = parse_js(src)
    modules = [imp.module for imp in out.imports]
    assert "./utils.js" in modules
    assert "react" in modules
