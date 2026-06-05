"""Ruby parser: module/class/method nesting + require(_relative)."""

from __future__ import annotations


def test_module_class_method_qualnames(parse_ruby):
    src = """module Foo
  class Bar
    def hello; end
  end
end
"""
    out = parse_ruby(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["Foo"].kind == "module"
    assert by_qual["Foo.Bar"].kind == "class"
    assert by_qual["Foo.Bar.hello"].kind == "method"


def test_require_relative_normalised(parse_ruby):
    src = 'require_relative "bar/baz"\nrequire "json"\n'
    out = parse_ruby(src)
    mods = {i.module for i in out.imports}
    assert "./bar/baz" in mods  # require_relative -> ./-prefixed
    assert "json" in mods  # require left bare (global load path)
