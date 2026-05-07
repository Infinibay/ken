"""Python parser: function/class/method/import extraction + docstring."""

from __future__ import annotations


def test_extracts_top_level_function(parse_python):
    src = '''def foo():
    """First-line doc.

    Second paragraph.
    """
    return 1
'''
    out = parse_python(src)
    assert len(out.symbols) == 1
    s = out.symbols[0]
    assert s.kind == "function"
    assert s.name == "foo"
    assert s.qualname == "foo"
    assert s.line_start == 1
    assert s.docstring == "First-line doc."


def test_extracts_class_with_methods_and_qualnames(parse_python):
    src = '''class Foo:
    """Class doc."""
    def bar(self):
        """Method doc."""
        pass

    def baz(self):
        return 2
'''
    out = parse_python(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert "Foo" in by_qual and by_qual["Foo"].kind == "class"
    assert "Foo.bar" in by_qual and by_qual["Foo.bar"].kind == "method"
    assert "Foo.baz" in by_qual
    assert by_qual["Foo"].docstring == "Class doc."
    assert by_qual["Foo.bar"].docstring == "Method doc."


def test_handles_decorated_function(parse_python):
    """`@deco` is wrapped in `decorated_definition` — parser must still
    surface the inner function."""
    src = '''@some_decorator
def decorated():
    """Doc."""
    pass
'''
    out = parse_python(src)
    names = [s.name for s in out.symbols]
    assert "decorated" in names


def test_extracts_imports(parse_python):
    src = '''import os
import sys, json
from typing import List
from . import sub
'''
    out = parse_python(src)
    modules = [imp.module for imp in out.imports]
    assert "os" in modules
    assert "sys" in modules
    assert "json" in modules
    assert "typing" in modules


def test_function_without_docstring(parse_python):
    src = "def silent():\n    return 0\n"
    out = parse_python(src)
    assert len(out.symbols) == 1
    assert out.symbols[0].docstring is None


def test_does_not_recurse_into_nested_functions(parse_python):
    """Per parser comment: nested functions inside a body aren't surfaced."""
    src = '''def outer():
    def inner():
        return 1
    return inner
'''
    out = parse_python(src)
    names = [s.name for s in out.symbols]
    assert names == ["outer"]
