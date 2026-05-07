"""Render: terse vs verbose, level caps, file outline."""

from __future__ import annotations

from ken.ranker import FindingItem, RankedItem, RankResult
from ken.ranker.output import _file_outline, _fit_block, render_block


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
    assert sum(1 for ln in out.splitlines() if ln.startswith("- f") and ".py" in ln) == 3
    assert sum(1 for ln in out.splitlines() if ln.startswith("- S")) == 2
    assert out.startswith("<context-rank>\nRelevant context:")
    assert "verbose=0" not in out
    assert "[5.0]" not in out
    assert " x" not in out


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
    assert "Outlines:" in out
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


def test_render_terse_hides_score_and_reason(conn):
    result = RankResult(files=[_file("src/a.py", 7.3, "reactive:read_edit")])
    out = render_block(conn, result, verbose=0)
    assert "src/a.py" in out
    assert "[7.3]" not in out
    assert "reactive:read_edit" not in out


def test_render_terse_includes_capped_finding_note(conn):
    result = RankResult(
        findings=[
            FindingItem("codex wiring", "Use --codex.", ["codex"], 3.2, "finding:1.00"),
            FindingItem("other", "Other note.", [], 3.1, "finding:0.99"),
        ]
    )

    out = render_block(conn, result, verbose=0)

    assert "Notes:" in out
    assert "- codex wiring" in out
    assert "finding:1.00" not in out
    assert "Other note" not in out


def test_render_verbose_includes_findings_with_truncated_content(conn):
    long = "x " * 200
    result = RankResult(
        findings=[FindingItem("codex wiring", long, ["codex"], 3.2, "finding:1.00")]
    )

    out = render_block(conn, result, verbose=1)

    assert "Findings:" in out
    assert "codex wiring [codex]" in out
    assert "finding:1.00" in out
    assert "…" in out


def test_render_respects_max_chars_with_valid_footer(conn):
    result = RankResult(files=[_file(f"src/file_{i}.py", 5.0 - i * 0.1) for i in range(8)])

    out = render_block(conn, result, verbose=2, max_chars=150)

    assert len(out) <= 150
    assert out.startswith("<context-rank verbose=2>")
    assert "truncated by context budget" in out
    assert out.endswith("</context-rank>")


def test_verbose_budget_keeps_ranked_symbols_before_outlines(conn, make_file, make_symbol):
    fid = make_file("src/large.py")
    for i in range(20):
        make_symbol(
            fid,
            name=f"very_long_function_name_{i}",
            qualname=f"VeryVerboseClass.very_long_function_name_{i}",
            line_start=i + 1,
        )
    result = RankResult(
        files=[_file("src/large.py", 5.0, "fuzzy:0.95")],
        symbols=[_sym("VeryVerboseClass.critical_entrypoint", 4.9, "explicit-symbol")],
    )

    out = render_block(conn, result, verbose=2, max_chars=420)

    assert len(out) <= 420
    assert "VeryVerboseClass.critical_entrypoint" in out
    assert "truncated" in out
    assert out.endswith("</context-rank>")


def test_fit_block_drops_whole_lines():
    block = "\n".join(
        [
            "<context-rank verbose=1>",
            "first line",
            "second line with enough text to overflow",
            "</context-rank>",
        ]
    )

    out = _fit_block(block, max_chars=80)

    assert len(out) <= 80
    assert "second line" not in out
    assert out.endswith("</context-rank>")


def test_fit_block_returns_empty_when_budget_cannot_fit_tags():
    block = "<context-rank verbose=1>\nuseful\n</context-rank>"

    assert _fit_block(block, max_chars=10) == ""
