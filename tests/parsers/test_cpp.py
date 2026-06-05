"""C++ parser: functions/methods/types + #include extraction."""

from __future__ import annotations


def test_namespace_function_and_class_members(parse_cpp):
    src = """#include <vector>
#include "util/helper.hpp"

namespace app {

/// Adds two ints.
int add(int a, int b) { return a + b; }

class Widget {
public:
  Widget();
  ~Widget();
  void render() const;
  int counter;
};

struct Point { int x; int y; };
enum class Mode { A, B };

}
"""
    out = parse_cpp(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["app.add"].kind == "function"
    assert by_qual["app.add"].docstring == "Adds two ints."
    assert by_qual["app.Widget"].kind == "class"
    assert by_qual["app.Widget.render"].kind == "method"
    assert by_qual["app.Point"].kind == "struct"
    assert by_qual["app.Mode"].kind == "enum"
    # data member is not a callable -> skipped
    assert "app.Widget.counter" not in by_qual


def test_include_quote_style_preserved(parse_cpp):
    src = '#include <vector>\n#include "util/helper.hpp"\n'
    out = parse_cpp(src)
    mods = {i.module for i in out.imports}
    assert "vector" in mods  # angle-bracket: bare
    assert '"util/helper.hpp"' in mods  # quoted: keeps the marker


def test_out_of_line_definitions(parse_cpp):
    src = """class Vec {
public:
  int size() const;
};

int Vec::size() const { return 0; }
"""
    out = parse_cpp(src)
    kinds = {(s.qualname, s.kind) for s in out.symbols}
    assert ("Vec", "class") in kinds
    assert ("Vec.size", "method") in kinds
