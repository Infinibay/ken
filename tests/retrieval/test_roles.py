import pytest

from ken.retrieval.passages import extract_passages


@pytest.mark.parametrize("path,name,expected", [
    ("client_test.go", "TestReconnect", "test"),
    ("spec/options/reject.spec.ts", None, "test"),
    ("lib/client.test.js", None, "test"),
    ("README.md", None, "documentation"),
    ("src/testing.py", "test_connection", "test"),
    ("src/testing.py", "test_connection_status", "test"),
    ("src/testing.py", "testify", "definition"),
    ("src/test.go", "Testable", "definition"),
    ("examples/connect.py", "main", "example"),
])
def test_role_uses_language_conventions_without_incidental_substring_matches(path, name, expected):
    from ken.retrieval.roles import classify_role
    assert classify_role(path, name) == expected


def test_rust_test_attributes_and_cfg_scope_are_structural_role_evidence():
    from ken.parsers.rust import parse_rust_file
    source = b'''fn production() { }
#[test]
fn direct() { assert!(true); }
#[cfg(test)]
mod support {
    fn helper() { }
    #[test]
    fn check() { helper(); }
}
'''
    parsed = parse_rust_file(source, "src/client.rs")
    by_name = {p.entity.qualname: p.role for p in extract_passages(source, parsed, path="src/client.rs")}
    assert by_name["production"] == "definition"
    assert by_name["direct"] == "test"
    assert by_name["helper"] == "test"
    assert by_name["check"] == "test"
    direct = next(s for s in parsed.scopes if s.symbol.qualname == "direct")
    assert "#[test]" in direct.annotations
    assert "#[test]" in direct.signature


def test_rust_comment_that_mentions_a_test_does_not_change_role():
    from ken.parsers.rust import parse_rust_file
    source = b"// #[test] is documented here, but this is production code.\nfn direct() {}\n"
    parsed = parse_rust_file(source, "src/client.rs")
    assert next(p for p in extract_passages(source, parsed, path="src/client.rs")
                if p.entity.qualname == "direct").role == "definition"
