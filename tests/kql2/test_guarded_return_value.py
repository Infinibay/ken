"""KQL2 value-flow candidates include values returned after terminal guards."""

from ken.kql2.service import search

QUERY = """language "kql/2"; module test.guarded_return;
query forwarded {
  callable $owner { name:"wrapper"; body {
    let $value = call $site { name:"lookup"; resolution:any; };
    return $value;
  } }
  select $owner;
}"""


def test_value_returned_after_raise_guard_is_a_candidate(tmp_path):
    """The candidate query sees flow across a guard with a terminal arm."""
    (tmp_path / "writer.py").write_text(
        "def wrapper(key):\n"
        "    value = lookup(key)\n"
        "    if value is None:\n"
        "        raise KeyError(key)\n"
        "    return value\n"
    )
    result = search(tmp_path, QUERY, path="writer.py", backend="indexed", cache_mb=0)
    assert len(result["rows"]) == 1
    assert result["unknown_candidates"] == 0


def test_guard_cannot_make_a_discarded_result_a_candidate(tmp_path):
    """A later return of another value remains a non-match."""
    (tmp_path / "writer.py").write_text(
        "def wrapper(key):\n"
        "    value = lookup(key)\n"
        "    if value is None:\n"
        "        raise KeyError(key)\n"
        "    return 0\n"
    )
    result = search(tmp_path, QUERY, path="writer.py", backend="indexed", cache_mb=0)
    assert result["rows"] == []


def test_unreachable_return_is_not_a_candidate(tmp_path):
    """Text after an unconditional raise cannot witness returned flow."""
    (tmp_path / "writer.py").write_text(
        "def wrapper(key):\n"
        "    value = lookup(key)\n"
        "    raise KeyError(key)\n"
        "    return value\n"
    )
    result = search(tmp_path, QUERY, path="writer.py", backend="indexed", cache_mb=0)
    assert result["rows"] == []
