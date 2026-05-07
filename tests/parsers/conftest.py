"""Fixtures for parser tests.

Each language module exposes ``parse_<lang>_file(bytes, path_hint) ->
ParsedFile``. We feed them inline source bytes and assert on the
returned symbols / imports — no temp files needed.
"""

from __future__ import annotations

import pytest

from ken.parsers.go import parse_go_file
from ken.parsers.java import parse_java_file
from ken.parsers.javascript import parse_js_file
from ken.parsers.python import parse_python_file
from ken.parsers.rust import parse_rust_file
from ken.parsers.typescript import parse_ts_file


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
