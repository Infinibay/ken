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
