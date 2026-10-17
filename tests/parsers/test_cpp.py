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


def test_conditional_declarations_preserve_all_branches_and_owners(parse_cpp):
    source = """#ifndef SAMPLE_HEADER
#define SAMPLE_HEADER
#include <vector>
namespace sample {
class Reader {
public:
#if FEATURE
  int read() { return 1; }
#else
  int read() { return 2; }
#endif
};
}
#endif
"""
    parsed = parse_cpp(source)
    readers = [symbol for symbol in parsed.symbols if symbol.qualname == "sample.Reader.read"]
    assert [(symbol.kind, symbol.line_start, symbol.line_end) for symbol in readers] == [
        ("method", 8, 8), ("method", 10, 10),
    ]
    assert [item.module for item in parsed.imports] == ["vector"]


def test_nested_type_declarations_keep_member_ownership(parse_cpp):
    parsed = parse_cpp("""namespace sample {
class Outer {
public:
  struct Inner {
    Inner() {}
    int read() { return 1; }
  };
};
}
""")
    by_qual = {symbol.qualname: symbol for symbol in parsed.symbols}
    assert by_qual["sample.Outer.Inner"].kind == "struct"
    constructor = by_qual["sample.Outer.Inner.Inner"]
    assert (constructor.kind, constructor.line_start, constructor.line_end) == ("constructor", 5, 5)
    assert by_qual["sample.Outer.Inner.read"].kind == "method"


def test_namespace_macro_recovery_does_not_invent_a_callable(parse_cpp):
    parsed = parse_cpp("""LIBRARY_NAMESPACE_BEGIN
namespace utility {
int read() {
  return 1;
}
}
LIBRARY_NAMESPACE_END
""")
    assert [(s.kind, s.qualname, s.line_start, s.line_end) for s in parsed.symbols] == [
        ("function", "utility.read", 3, 5),
    ]


def test_local_types_have_callable_owners_without_fake_nested_functions(parse_cpp):
    parsed = parse_cpp("""namespace sample {
void run() {
  if (true) {
    struct Local {
      Local() {}
      int read() { return 1; }
    };
  }
  LIBRARY_FOREACH(index) { use(index); }
  try { work(); } catch (...) { recover(); }
}
}
""")
    by_qual = {symbol.qualname: symbol for symbol in parsed.symbols}
    assert set(by_qual) == {"sample.run", "sample.run.Local", "sample.run.Local.Local", "sample.run.Local.read"}
    constructor = by_qual["sample.run.Local.Local"]
    assert (constructor.kind, constructor.line_start, constructor.line_end) == ("constructor", 5, 5)
    assert by_qual["sample.run.Local.read"].kind == "method"


def test_friend_function_belongs_to_enclosing_namespace_even_in_nested_types(parse_cpp):
    parsed = parse_cpp("""namespace sample {
class Outer {
  class Inner {
    friend void swap(Inner& left, Inner& right) { left.read(right); }
  };
};
}
""")
    friends = [symbol for symbol in parsed.symbols if symbol.name == "swap"]
    assert [(s.kind, s.qualname, s.line_start, s.line_end) for s in friends] == [
        ("function", "sample.swap", 4, 4),
    ]
