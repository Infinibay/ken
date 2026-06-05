"""C# parser: types/methods + `using` namespace imports."""

from __future__ import annotations


def test_class_and_method(parse_csharp):
    src = "namespace App.Services { class Foo { void Bar() {} } }\n"
    out = parse_csharp(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["Foo"].kind == "class"
    assert by_qual["Foo.Bar"].kind == "method"


def test_using_imports(parse_csharp):
    src = "using System;\nusing App.Models;\n"
    out = parse_csharp(src)
    mods = {i.module for i in out.imports}
    assert "System" in mods
    assert "App.Models" in mods
