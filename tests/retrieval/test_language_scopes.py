import pytest

from ken.parsers import detect_language


@pytest.mark.parametrize("path,source", [
    ("x.js", "/** Bounded retries.\n * Preserve the last failure. */\nfunction retryRequest(n) {\n return n + 1;\n}\n"),
    ("x.ts", "/** Bounded retries.\n * Preserve the last failure. */\nfunction retryRequest(n: number): number {\n return n + 1;\n}\n"),
    ("x.go", "package client\n// Bounded retries.\n// Preserve the last failure.\nfunc retryRequest(n int) int {\n return n + 1\n}\n"),
    ("x.rs", "/// Bounded retries.\n/// Preserve the last failure.\nfn retry_request(n: i32) -> i32 {\n n + 1\n}\n"),
    ("X.java", "class Client {\n /** Bounded retries.\n * Preserve the last failure. */\n int retryRequest(int n) {\n return n + 1;\n }\n}\n"),
])
def test_each_language_preserves_signature_and_full_documentation(path, source):
    from pathlib import Path
    _, parse = detect_language(Path(path))
    parsed = parse(source.encode(), path)
    callables = [s for s in parsed.scopes if s.symbol.kind in ("function", "method")]
    assert callables
    scope = callables[0]
    assert "Bounded retries" in scope.documentation
    assert "Preserve the last failure" in scope.documentation
    assert "retry" in scope.signature
    assert scope.statements


@pytest.mark.parametrize("path", ["x.js", "x.ts"])
def test_assigned_and_nested_callables_have_their_own_source_responsibility(path):
    from pathlib import Path
    from ken.retrieval.passages import extract_passages
    source = b'''export default (options, Type) => {
  const proto = Type.prototype
  proto.load = function(input) {
    function normalize(value) {
      return value.trim()
    }
    return normalize(input)
  }
  proto.save = (value) => {
    store(value)
  }
}
'''
    _, parse = detect_language(Path(path))
    parsed = parse(source, path)
    # Retain the compact outline; correct its previously lost lexical owner.
    assert [s.qualname for s in parsed.symbols] == ["proto.load.normalize"]
    by_name = {s.symbol.qualname: s for s in parsed.scopes}
    assert set(by_name) == {"proto.load", "proto.load.normalize", "proto.save"}
    assert by_name["proto.load.normalize"].owner == "proto.load"
    assert "proto.save = (value) =>" in by_name["proto.save"].signature
    assert by_name["proto.load"].implementation_start_line == 4
    passages = extract_passages(source, parsed, path=path)
    load = [p for p in passages if p.entity.qualname == "proto.load"]
    assert load and all("value.trim()" not in p.fields["body"] for p in load)
    assert any(p.entity.qualname == "proto.load.normalize" and "value.trim()" in p.fields["body"]
               for p in passages)


@pytest.mark.parametrize("path", ["x.js", "x.ts"])
def test_computed_runtime_target_does_not_invent_a_callable_identity(path):
    from pathlib import Path
    _, parse = detect_language(Path(path))
    parsed = parse(b"target[key] = () => { return 1 }\n", path)
    assert parsed.scopes == []


@pytest.mark.parametrize('path', ['x.js', 'x.ts'])
@pytest.mark.parametrize('declaration', ['const', 'let', 'var', 'export const'])
def test_assigned_callable_signature_excludes_body_and_records_executable_boundary(path, declaration):
    from pathlib import Path
    from ken.retrieval.passages import extract_passages
    source = (declaration + ''' retry = (value) => {
  // This comment describes the implementation.
  const next = value + 1
  return next
}
''').encode()
    _, parse = detect_language(Path(path))
    parsed = parse(source, path)
    scope, = [s for s in parsed.scopes if s.symbol.qualname == 'retry']
    assert 'retry = (value) =>' in scope.signature
    assert 'const next' not in scope.signature
    assert 'return next' not in scope.signature
    assert scope.implementation_start_line == 3
    assert scope.statements == [(2, 2), (3, 3), (4, 4)]
    passages = extract_passages(source, parsed, path=path)
    assert any(p.span.start_line == 3 for p in passages)
    assert all('return next' not in p.fields['signature'] for p in passages)
