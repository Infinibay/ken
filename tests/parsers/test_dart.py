"""Dart parser: classes / members / mixins / enums / extensions / imports."""

from __future__ import annotations


def test_extracts_class_with_members_and_doc(parse_dart):
    src = """import 'dart:math';

/// A greeter.
class Greeter extends Base {
  final String name;
  Greeter(this.name);
  /// Say hi.
  String hello() => 'hi $name';
  static int count() => 0;
  int get value => 1;
  set value(int v) {}
}
"""
    out = parse_dart(src)
    by_qual = {s.qualname: s for s in out.symbols}

    assert by_qual["Greeter"].kind == "class"
    assert by_qual["Greeter"].docstring == "A greeter."

    assert by_qual["Greeter.hello"].kind == "method"
    assert by_qual["Greeter.hello"].docstring == "Say hi."
    # The method span reaches over the `=> ...` body sibling.
    assert by_qual["Greeter.hello"].line_end >= by_qual["Greeter.hello"].line_start

    assert by_qual["Greeter.count"].kind == "method"
    assert by_qual["Greeter.value"].kind in ("getter", "setter")

    ctors = [s for s in out.symbols if s.kind == "constructor"]
    assert [c.name for c in ctors] == ["Greeter"]


def test_extracts_mixin_enum_extension_typedef(parse_dart):
    src = """mixin Walk {}
abstract class Animal {}
enum Color { red, blue }
typedef IntList = List<int>;
extension StringX on String {
  bool get isBlank => trim().isEmpty;
}
"""
    out = parse_dart(src)
    by_qual = {s.qualname: s for s in out.symbols}

    assert by_qual["Walk"].kind == "mixin"
    assert by_qual["Animal"].kind == "class"
    assert by_qual["Color"].kind == "enum"
    assert by_qual["IntList"].kind == "typedef"
    assert by_qual["StringX"].kind == "extension"
    # Extension members are scoped under the extension name.
    assert by_qual["StringX.isBlank"].kind == "getter"


def test_extracts_top_level_function(parse_dart):
    src = """/// Entry point.
void main() {
  print('hi');
}

int square(int x) => x * x;
"""
    out = parse_dart(src)
    by_qual = {s.qualname: s for s in out.symbols}

    assert by_qual["main"].kind == "function"
    assert by_qual["main"].docstring == "Entry point."
    assert by_qual["square"].kind == "function"


def test_extracts_imports_and_exports(parse_dart):
    src = """import 'dart:math';
import 'package:flutter/material.dart' as m;
export 'src/foo.dart';

void main() {}
"""
    out = parse_dart(src)
    modules = [imp.module for imp in out.imports]

    assert "dart:math" in modules
    assert "package:flutter/material.dart" in modules
    assert "src/foo.dart" in modules
