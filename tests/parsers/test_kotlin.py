"""Kotlin parser: classes/methods, top-level functions, dotted imports."""

from __future__ import annotations


def test_class_method_and_top_level_function(parse_kotlin):
    src = """package com.foo

class Widget {
    fun render() {}
}

fun topLevel() {}
"""
    out = parse_kotlin(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["Widget"].kind == "class"
    assert by_qual["Widget.render"].kind == "method"
    assert by_qual["topLevel"].kind == "function"


def test_dotted_imports(parse_kotlin):
    src = "package com.foo\nimport com.bar.Baz\nimport kotlin.collections.List\n"
    out = parse_kotlin(src)
    mods = {i.module for i in out.imports}
    assert "com.bar.Baz" in mods
    assert "kotlin.collections.List" in mods
