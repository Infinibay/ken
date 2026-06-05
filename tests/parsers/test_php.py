"""PHP parser: classes/methods, `use` namespaces, require includes."""

from __future__ import annotations


def test_class_and_method(parse_php):
    src = "<?php\nnamespace App\\Services;\nclass Foo {\n  public function bar() {}\n}\n"
    out = parse_php(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["Foo"].kind == "class"
    assert by_qual["Foo.bar"].kind == "method"


def test_use_namespace_import(parse_php):
    src = "<?php\nuse App\\Models\\User;\nuse Illuminate\\Support\\Str;\n"
    out = parse_php(src)
    mods = {i.module for i in out.imports}
    assert "App\\Models\\User" in mods
    assert "Illuminate\\Support\\Str" in mods
