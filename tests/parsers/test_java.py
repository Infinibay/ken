"""Java parser: class / interface / methods / javadoc / imports."""

from __future__ import annotations


def test_extracts_class_with_methods_and_javadoc(parse_java):
    src = '''package com.example;

import java.util.List;

/**
 * Greet someone.
 */
public class Greeter {
    /**
     * Say hi.
     */
    public String hello(String name) { return "hi " + name; }

    public Greeter() {}
}
'''
    out = parse_java(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert "Greeter" in by_qual
    assert by_qual["Greeter"].kind == "class"
    assert by_qual["Greeter"].docstring == "Greet someone."
    assert "Greeter.hello" in by_qual
    assert by_qual["Greeter.hello"].docstring == "Say hi."
    # Constructor recorded with kind="constructor".
    ctors = [s for s in out.symbols if s.kind == "constructor"]
    assert len(ctors) == 1
    assert ctors[0].name == "Greeter"


def test_extracts_interface_and_enum(parse_java):
    src = '''interface Drawable {
    void draw();
}

enum Color { RED, BLUE }
'''
    out = parse_java(src)
    by_kind = {s.kind for s in out.symbols}
    assert "interface" in by_kind
    assert "enum" in by_kind


def test_extracts_imports(parse_java):
    src = '''import java.util.List;
import java.util.Map;
import static java.lang.Math.PI;
import com.foo.bar.*;

class X {}
'''
    out = parse_java(src)
    modules = [imp.module for imp in out.imports]
    assert "java.util.List" in modules
    assert "java.util.Map" in modules
    # `static java.lang.Math.PI` → "java.lang.Math.PI"
    assert "java.lang.Math.PI" in modules
    # Wildcard import: trailing `.*` is stripped.
    assert "com.foo.bar" in modules
