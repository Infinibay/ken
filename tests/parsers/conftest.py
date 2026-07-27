"""Fixtures for parser tests.

Each language module exposes ``parse_<lang>_file(bytes, path_hint) ->
ParsedFile``. We feed them inline source bytes and assert on the
returned symbols / imports — no temp files needed.
"""

from __future__ import annotations

import pytest

from ken.parsers.bash import parse_bash_file
from ken.parsers.c import parse_c_file
from ken.parsers.cpp import parse_cpp_file
from ken.parsers.csharp import parse_csharp_file
from ken.parsers.css import parse_css_file
from ken.parsers.dart import parse_dart_file
from ken.parsers.go import parse_go_file
from ken.parsers.graphql import parse_graphql_file
from ken.parsers.html import parse_html_file
from ken.parsers.java import parse_java_file
from ken.parsers.javascript import parse_js_file
from ken.parsers.kotlin import parse_kotlin_file
from ken.parsers.php import parse_php_file
from ken.parsers.powershell import parse_powershell_file
from ken.parsers.python import parse_python_file
from ken.parsers.ruby import parse_ruby_file
from ken.parsers.rust import parse_rust_file
from ken.parsers.sql import parse_sql_file
from ken.parsers.typescript import parse_ts_file


@pytest.fixture
def parse_c():
    def _p(src: str):
        return parse_c_file(src.encode("utf-8"), "inline.c")
    return _p


@pytest.fixture
def parse_python():
    def _p(src: str) -> "ParsedFile":  # noqa: F821
        return parse_python_file(src.encode("utf-8"), "inline.py")
    return _p


@pytest.fixture
def parse_rust():
    def _p(src: str):
        return parse_rust_file(src.encode("utf-8"), "inline.rs")
    return _p


@pytest.fixture
def parse_js():
    def _p(src: str):
        return parse_js_file(src.encode("utf-8"), "inline.js")
    return _p


@pytest.fixture
def parse_ts():
    def _p(src: str, *, tsx: bool = False):
        hint = "inline.tsx" if tsx else "inline.ts"
        return parse_ts_file(src.encode("utf-8"), hint)
    return _p


@pytest.fixture
def parse_go():
    def _p(src: str):
        return parse_go_file(src.encode("utf-8"), "inline.go")
    return _p


@pytest.fixture
def parse_java():
    def _p(src: str):
        return parse_java_file(src.encode("utf-8"), "Inline.java")
    return _p


@pytest.fixture
def parse_dart():
    def _p(src: str):
        return parse_dart_file(src.encode("utf-8"), "inline.dart")
    return _p


@pytest.fixture
def parse_bash():
    def _p(src: str):
        return parse_bash_file(src.encode("utf-8"), "inline.sh")
    return _p


@pytest.fixture
def parse_cpp():
    def _p(src: str):
        return parse_cpp_file(src.encode("utf-8"), "inline.cpp")
    return _p


@pytest.fixture
def parse_csharp():
    def _p(src: str):
        return parse_csharp_file(src.encode("utf-8"), "Inline.cs")
    return _p


@pytest.fixture
def parse_css():
    def _p(src: str):
        return parse_css_file(src.encode("utf-8"), "inline.css")
    return _p


@pytest.fixture
def parse_html():
    def _p(src: str):
        return parse_html_file(src.encode("utf-8"), "inline.html")
    return _p


@pytest.fixture
def parse_graphql():
    def _p(src: str):
        return parse_graphql_file(src.encode("utf-8"), "inline.graphql")
    return _p


@pytest.fixture
def parse_kotlin():
    def _p(src: str):
        return parse_kotlin_file(src.encode("utf-8"), "inline.kt")
    return _p


@pytest.fixture
def parse_php():
    def _p(src: str):
        return parse_php_file(src.encode("utf-8"), "inline.php")
    return _p


@pytest.fixture
def parse_powershell():
    def _p(src: str):
        return parse_powershell_file(src.encode("utf-8"), "inline.ps1")
    return _p


@pytest.fixture
def parse_ruby():
    def _p(src: str):
        return parse_ruby_file(src.encode("utf-8"), "inline.rb")
    return _p


@pytest.fixture
def parse_sql():
    def _p(src: str):
        return parse_sql_file(src.encode("utf-8"), "inline.sql")
    return _p
