"""Bash parser: function definitions + `source` / `.` imports."""

from __future__ import annotations


def test_extracts_functions_both_syntaxes(parse_bash):
    src = """# greet a user
greet() {
  echo "hi $1"
}

function deploy {
  echo deploy
}
"""
    out = parse_bash(src)
    by_name = {s.name: s for s in out.symbols}
    assert by_name["greet"].kind == "function"
    assert by_name["greet"].docstring == "greet a user"
    assert by_name["deploy"].kind == "function"


def test_source_and_dot_are_imports(parse_bash):
    src = 'source ./lib/utils.sh\n. "$HOME/config.sh"\nsource /etc/profile.d/foo.sh\n'
    out = parse_bash(src)
    mods = [i.module for i in out.imports]
    assert "./lib/utils.sh" in mods
    assert "$HOME/config.sh" in mods
    assert "/etc/profile.d/foo.sh" in mods
    assert not out.symbols


def test_nested_function_is_method(parse_bash):
    src = "outer() {\n  inner() { echo nested; }\n  echo hi\n}\n"
    out = parse_bash(src)
    by_qual = {s.qualname: s for s in out.symbols}
    assert by_qual["outer"].kind == "function"
    assert by_qual["outer.inner"].kind == "method"
