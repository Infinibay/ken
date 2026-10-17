"""Content resolves ambiguous .h files without changing unambiguous extensions."""
from pathlib import Path

import pytest

from ken.parsers import detect_language


@pytest.mark.parametrize("source", [
    b"namespace sample { int read() { return 1; } }",
    b"class Reader { public: int read() { return 1; } };",
    b"template<class T> T read(T value) { return value; }",
    b"using Value = unsigned long;",
    b"int& read();",
])
def test_cpp_header_uses_structural_language_evidence(source):
    language, parser = detect_language(Path("api.h"), source=source)
    assert language == "cpp"
    assert parser.__name__ == "parse_cpp_file"


@pytest.mark.parametrize("source", [
    b"#ifndef HEADER\n#define HEADER\nstruct Reader { int size; };\nint read(void);\n#endif\n",
    b'/* namespace sample { class Reader {}; } */\nconst char *label = "template<class T>";\nint read(void);',
    b"int class = 0; int namespace = 1; int template = 2;",
])
def test_c_header_keeps_c_parser(source):
    language, parser = detect_language(Path("api.h"), source=source)
    assert language == "c"
    assert parser.__name__ == "parse_c_file"


def test_unambiguous_extension_and_extension_only_lookup_are_preserved():
    assert detect_language(Path("api.h"))[0] == "c"
    assert detect_language(Path("source.c"), source=b"namespace fake {}")[0] == "c"
    assert detect_language(Path("source.hpp"), source=b"int read(void);")[0] == "cpp"
