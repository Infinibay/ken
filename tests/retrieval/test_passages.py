from __future__ import annotations

import hashlib

from ken.parsers.python import parse_python_file


def extract(source: bytes, path="auth.py", budget=64):
    from ken.retrieval.passages import PassagePolicy, extract_passages
    return extract_passages(source, parse_python_file(source, path), path=path,
                            policy=PassagePolicy(max_tokens=budget))


def test_long_function_preserves_late_behavior_anchor():
    src = ("def process(values):\n" + "".join(f"    values.append({i})\n" for i in range(80))
           + "    raise ValueError('connection was reset')\n").encode()
    passages = extract(src)
    assert len(passages) > 5
    assert all(p.entity.qualname == "process" for p in passages)
    assert any("connection was reset" in p.fields["body"] for p in passages)
    visible = {line for p in passages for line in range(p.span.start_line, p.span.end_line + 1)}
    assert set(range(1, 83)) <= visible


def test_nested_and_homonymous_owners_are_distinct():
    src = b"class Client:\n    def read(self):\n        return 1\ndef outer():\n    def read():\n        return 2\n    return read\n"
    passages = extract(src)
    identities = {(p.entity.kind, p.entity.qualname, p.entity.owner) for p in passages}
    assert ("method", "Client.read", "Client") in identities
    assert ("function", "outer.read", "outer") in identities
    for p in passages:
        if p.entity.qualname == "outer":
            assert "return 2" not in p.fields["body"]


def test_full_docs_and_signature_are_separate_from_source_body():
    src = b'def adjust(value: int) -> int:\n    """Short.\n\n    Detailed explanation of validation.\n    """\n    return value + 1\n'
    passages = extract(src)
    assert any("Detailed explanation" in p.fields["documentation"] for p in passages)
    assert all("def adjust(value: int)" in p.fields["signature"] for p in passages)
    assert all(p.source_hash == hashlib.sha256(src).hexdigest() for p in passages)


def test_decorators_overloads_unicode_and_crlf_keep_source_coordinates():
    src = '@cache\r\ndef read():\r\n    return "niño"\r\ndef read():\r\n    return "otra"\r\n'.encode()
    passages = extract(src)
    functions = [p for p in passages if p.entity.qualname == "read"]
    assert {p.entity.definition_ordinal for p in functions} == {0, 1}
    lines = src.decode().splitlines()
    for p in passages:
        assert p.fields["body"] == "\n".join(lines[p.span.start_line - 1:p.span.end_line])


def test_module_fragment_has_no_fabricated_symbol():
    passages = extract(b"ENVIRONMENT = 'PROJECT_AUTH_TOKEN'\n")
    assert passages[0].entity.kind == "module"
    assert passages[0].entity.qualname is None
    assert "PROJECT_AUTH_TOKEN" in passages[0].fields["body"]


def test_token_budget_is_enforced_without_losing_lines():
    passages = extract(b"def f():\n    x = 1\n    y = 2\n    z = 3\n", budget=6)
    assert len(passages) >= 3
    assert all(p.span.end_line >= p.span.start_line for p in passages)


def test_parser_legacy_symbols_remain_compatible_but_scopes_include_closures():
    source = b"def outer():\n    def inner():\n        return 1\n    return inner\n"
    parsed = parse_python_file(source, "x.py")
    assert [s.name for s in parsed.symbols] == ["outer"]
    assert [scope.symbol.qualname for scope in parsed.scopes] == ["outer", "outer.inner"]


def test_binary_assets_do_not_become_behavior_passages():
    from ken.parsers.types import ParsedFile
    from ken.retrieval.passages import extract_passages
    assert extract_passages(b"PNG\x00\xff\x00image", ParsedFile(), path="logo.png") == []


def test_passages_prefer_complete_statements_and_separate_documentation():
    source = b'def clean(value):\n    """Clean a value."""\n    result = operation(\n        value,\n        strict=True,\n    )\n    return result\n'
    passages = extract(source, budget=24)
    assert all(p.implementation_start_line == 3 for p in passages)
    assert any(p.span.start_line == 3 and p.span.end_line >= 6 for p in passages)
    assert all(not (p.span.start_line < 3 <= p.span.end_line) for p in passages)


def test_non_utf8_bytes_without_nul_do_not_become_source_passages():
    from ken.parsers.types import ParsedFile
    from ken.retrieval.passages import extract_passages

    # A compressed fuzz input can contain no NUL and still be binary.
    assert extract_passages(b"\x95compressed\xff\n", ParsedFile(),
                            path="fuzz/deflate-stream.input") == []
    assert extract_passages(b"// broken \xff\nfn main() {}\n", ParsedFile(),
                            path="broken.zig") == []


def test_valid_utf8_unknown_extension_keeps_faithful_source(tmp_path):
    from ken.parsers.types import ParsedFile
    from ken.retrieval.passages import extract_passages
    from ken.retrieval.piece_catalog import SourceCatalog

    source = "Unicode niño λ 日本語\r\nsecond line\r\n".encode()
    (tmp_path / "example.input").write_bytes(source)
    passages = extract_passages(source, ParsedFile(), path="example.input")
    assert len(passages) == 1
    assert passages[0].fields["body"] == "Unicode niño λ 日本語\nsecond line"
    catalog = SourceCatalog(tmp_path, {passages[0].entity: passages})
    assert catalog.lines["example.input"] == ["Unicode niño λ 日本語", "second line"]
