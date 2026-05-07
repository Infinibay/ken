"""Explicit-mention channel: regex + DB lookup."""

from __future__ import annotations

from ken.ranker.channels import (
    EXPLICIT_FILE_FROM_SYMBOL,
    EXPLICIT_FILE_SCORE,
    EXPLICIT_SYMBOL_SCORE,
    explicit_mentions,
)


def test_path_mention_lifts_file(conn, make_file):
    make_file("src/auth.py")
    files, syms = explicit_mentions(conn, "fix the bug in src/auth.py")
    assert len(files) == 1
    assert files[0].target == "src/auth.py"
    assert files[0].score == EXPLICIT_FILE_SCORE
    assert syms == []


def test_bare_filename_resolves_via_suffix(conn, make_file):
    make_file("src/deep/nested/module.py")
    files, _ = explicit_mentions(conn, "what does module.py do?")
    assert len(files) == 1
    assert files[0].target == "src/deep/nested/module.py"


def test_path_with_line_number(conn, make_file):
    make_file("src/auth.py")
    files, _ = explicit_mentions(conn, "the bug is at src/auth.py:42")
    assert len(files) == 1
    assert files[0].target == "src/auth.py"


def test_unknown_extension_ignored(conn, make_file):
    make_file("src/auth.py")
    # `.bin` not in _KNOWN_EXTS → not even tried as path.
    files, _ = explicit_mentions(conn, "see config.bin and src/auth.py")
    assert len(files) == 1
    assert files[0].target == "src/auth.py"


def test_camelcase_lifts_symbol(conn, make_file, make_symbol):
    fid = make_file("src/auth.py")
    make_symbol(fid, name="Session", kind="class", line_start=10)
    files, syms = explicit_mentions(conn, "what does Session do?")
    assert len(syms) == 1
    assert "Session" in syms[0].target
    assert syms[0].score == EXPLICIT_SYMBOL_SCORE
    # File got a smaller boost from the symbol mention.
    assert any(
        f.target == "src/auth.py" and f.score == EXPLICIT_FILE_FROM_SYMBOL
        for f in files
    )


def test_backtick_quoted_lifts_symbol(conn, make_file, make_symbol):
    fid = make_file("src/auth.py")
    make_symbol(fid, name="login", qualname="login", kind="function")
    files, syms = explicit_mentions(conn, "call `login` to authenticate")
    assert len(syms) == 1
    assert "login" in syms[0].target


def test_qualname_match(conn, make_file, make_symbol):
    fid = make_file("src/auth.py")
    make_symbol(fid, name="expire", qualname="Session.expire", kind="method")
    _, syms = explicit_mentions(conn, "fix Session.expire — it's broken")
    assert len(syms) == 1
    assert "Session.expire" in syms[0].target


def test_no_mentions_returns_empty(conn, make_file):
    make_file("src/auth.py")
    files, syms = explicit_mentions(conn, "hello world")
    assert files == []
    assert syms == []


def test_short_token_filtered(conn, make_file, make_symbol):
    """Identifiers < 3 chars are skipped to avoid noise like "X" / "OK"."""
    fid = make_file("src/a.py")
    make_symbol(fid, name="X", qualname="X")
    _, syms = explicit_mentions(conn, "the value is X")
    assert syms == []
