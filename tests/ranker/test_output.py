"""Render: terse vs verbose, level caps, file outline."""

from __future__ import annotations

from ken.ranker import RankedItem, RankResult
from ken.ranker.output import _file_outline, render_block


def _file(target: str, score: float, reason: str = "x") -> RankedItem:
    return RankedItem(target=target, target_type="file", score=score, reason=reason)


def _sym(target: str, score: float, reason: str = "x") -> RankedItem:
    return RankedItem(target=target, target_type="symbol", score=score, reason=reason)


def test_render_empty_returns_empty_string(conn):
    assert render_block(conn, RankResult(), verbose=0) == ""
    assert render_block(conn, RankResult(), verbose=1) == ""
    assert render_block(conn, RankResult(), verbose=2) == ""


def test_render_terse_caps_files_and_symbols(conn):
    result = RankResult(
        files=[_file(f"f{i}.py", 5.0 - i * 0.1) for i in range(10)],
        symbols=[_sym(f"S{i}", 4.0 - i * 0.1) for i in range(10)],
    )
    out = render_block(conn, result, verbose=0)
    # verbose=0: 3 files, 0 outline, 2 symbols
    file_lines = [ln for ln in out.splitlines() if ln.endswith(".py [5.0] x") or ln.startswith("f")]
    assert sum(1 for ln in out.splitlines() if ln.startswith("f") and ".py" in ln) == 3
    # symbol lines start with "  ↳"
    assert sum(1 for ln in out.splitlines() if ln.startswith("  ↳")) == 2
    assert "verbose=0" in out


def test_render_verbose_l1_includes_outline(conn, make_file, make_symbol):
    fid = make_file("src/a.py")
    make_symbol(fid, name="f1", qualname="f1", line_start=1)
    make_symbol(fid, name="f2", qualname="f2", line_start=2)
    make_symbol(fid, name="f3", qualname="f3", line_start=3)
    make_symbol(fid, name="f4", qualname="f4", line_start=4)

    result = RankResult(files=[_file("src/a.py", 5.0)])
    out = render_block(conn, result, verbose=1)
    # 3-line outline at level 1.
    outline_lines = [ln for ln in out.splitlines() if ln.startswith("       ")]
    assert len(outline_lines) == 3
    assert "verbose=1" in out


def test_render_verbose_l2_more_outline(conn, make_file, make_symbol):
    fid = make_file("src/a.py")
    for i in range(15):
        make_symbol(fid, name=f"f{i}", qualname=f"f{i}", line_start=i + 1)
    result = RankResult(files=[_file("src/a.py", 5.0)])
    out = render_block(conn, result, verbose=2)
    outline_lines = [ln for ln in out.splitlines() if ln.startswith("       ")]
    assert len(outline_lines) == 12  # cap at level 2
    assert "verbose=2" in out


def test_render_invalid_verbose_falls_back_to_l1(conn):
    result = RankResult(files=[_file("src/a.py", 5.0)])
    out = render_block(conn, result, verbose=99)
    assert "verbose=1" in out


def test_file_outline_respects_limit(conn, make_file, make_symbol):
    fid = make_file("src/a.py")
    for i in range(10):
        make_symbol(fid, name=f"f{i}", qualname=f"f{i}", line_start=i + 1)
    out = _file_outline(conn, "src/a.py", 3)
    assert len(out) == 3


def test_file_outline_empty_when_no_symbols(conn, make_file):
    make_file("src/empty.py")
    assert _file_outline(conn, "src/empty.py", 5) == []


def test_render_includes_score_and_reason(conn):
    result = RankResult(files=[_file("src/a.py", 7.3, "reactive:read_edit")])
    out = render_block(conn, result, verbose=0)
    assert "src/a.py" in out
    assert "[7.3]" in out
    assert "reactive:read_edit" in out
