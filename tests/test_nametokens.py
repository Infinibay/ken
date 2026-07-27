"""The lexical channel moved its tokenisation from query time to index time.

That is only allowed to be a speed change. The test that matters is therefore
not "does the posting list return something" but "does it return exactly what
the brute-force sweep returned" — same targets, same scores, same reasons. Both
paths are still in the tree (the sweep is the fallback for un-migrated indexes),
so they can be run against each other directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ken.db import connect, get_meta, init_schema, set_meta
from ken.indexer import rebuild_name_tokens
from ken.nametokens import NAME_TOKEN_VERSION, name_tokens, project_stopwords
from ken.ranker import channels


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "myproj"
    root.mkdir()
    (root / ".ken").mkdir()
    conn = connect(root / ".ken" / "ken.db")
    init_schema(conn)
    yield root, conn
    conn.close()


def _populate(conn, entries):
    """entries: [(path, [(kind, qualname, name), ...])]"""
    for path, symbols in entries:
        cur = conn.execute(
            "INSERT INTO ci_files(path, content_hash, mtime, indexed_at) "
            "VALUES(?, x'00', 0, 0)",
            (path,),
        )
        fid = int(cur.lastrowid)
        for kind, qualname, name in symbols:
            conn.execute(
                "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end) "
                "VALUES(?, ?, ?, ?, 1, 2)",
                (fid, kind, name, qualname),
            )


CORPUS = [
    ("src/scheduler/core.py", [
        ("function", "pick_next_task", "pick_next_task"),
        ("class", "TaskScheduler", "TaskScheduler"),
    ]),
    ("kernel/sched/fair.c", [
        ("function", "pick_next_entity", "pick_next_entity"),
    ]),
    ("src/parser/html.py", [
        ("function", "parse_html_file", "parse_html_file"),
        ("method", "HtmlParser.feed", "feed"),
    ]),
    ("docs/README.md", []),
]

QUERIES = [
    "how does the scheduler pick the next task",
    "TaskScheduler",
    "parsear el html",
    "feed",
    "something entirely unrelated zzzz",
    "pick_next_task",
]


def _both_paths(conn, root, prompt):
    """Run the channel with the posting list on, then off, and return both."""
    stop = project_stopwords(root)
    tokens = name_tokens(prompt, extra_stopwords=stop)

    set_meta(conn, "name_token_version", str(NAME_TOKEN_VERSION))
    fast_f = channels._lexical_files(conn, tokens, extra_stopwords=stop)
    fast_s = channels._lexical_symbols(conn, tokens, extra_stopwords=stop)

    set_meta(conn, "name_token_version", "0")  # force the fallback sweep
    slow_f = channels._lexical_files(conn, tokens, extra_stopwords=stop)
    slow_s = channels._lexical_symbols(conn, tokens, extra_stopwords=stop)
    return (fast_f, fast_s), (slow_f, slow_s)


def _key(items):
    return sorted((i.target, round(i.score, 9), i.reason) for i in items)


@pytest.mark.parametrize("prompt", QUERIES)
def test_posting_list_matches_the_brute_force_sweep(project, prompt):
    root, conn = project
    _populate(conn, CORPUS)
    rebuild_name_tokens(conn, root)

    (fast_f, fast_s), (slow_f, slow_s) = _both_paths(conn, root, prompt)
    assert _key(fast_f) == _key(slow_f), prompt
    assert _key(fast_s) == _key(slow_s), prompt


def test_the_corpus_actually_exercises_both_branches(project):
    """A guard on the guard: identical-but-empty would pass every assertion."""
    root, conn = project
    _populate(conn, CORPUS)
    rebuild_name_tokens(conn, root)
    stop = project_stopwords(root)
    tokens = name_tokens("how does the scheduler pick the next task", extra_stopwords=stop)
    set_meta(conn, "name_token_version", str(NAME_TOKEN_VERSION))
    assert channels._lexical_symbols(conn, tokens, extra_stopwords=stop)
    assert channels._lexical_files(conn, tokens, extra_stopwords=stop)


def test_alias_expansion_survives_the_round_trip(project):
    """`scheduler` is stored expanded to `sched`, so a prompt saying `sched`
    still finds it. That symmetry is the reason indexer and ranker must share
    one tokeniser."""
    root, conn = project
    _populate(conn, CORPUS)
    rebuild_name_tokens(conn, root)
    stop = project_stopwords(root)
    set_meta(conn, "name_token_version", str(NAME_TOKEN_VERSION))
    hits = channels._lexical_files(
        conn, name_tokens("sched", extra_stopwords=stop), extra_stopwords=stop
    )
    assert any("scheduler" in h.target for h in hits)


def test_stale_stamp_falls_back_instead_of_returning_nothing(project):
    """An index built by an older tokeniser must degrade to slow, never to empty."""
    root, conn = project
    _populate(conn, CORPUS)
    # postings deliberately never built
    stop = project_stopwords(root)
    tokens = name_tokens("scheduler", extra_stopwords=stop)
    assert get_meta(conn, "name_token_version") is None
    assert channels._lexical_files(conn, tokens, extra_stopwords=stop)


def test_deleting_a_file_sweeps_its_symbol_postings(project):
    root, conn = project
    _populate(conn, CORPUS)
    rebuild_name_tokens(conn, root)
    before = conn.execute("SELECT COUNT(*) FROM ci_name_tokens").fetchone()[0]
    conn.execute("DELETE FROM ci_files WHERE path = 'src/scheduler/core.py'")
    after = conn.execute("SELECT COUNT(*) FROM ci_name_tokens").fetchone()[0]
    assert after < before
    # Nothing may survive pointing at a row that no longer exists.
    orphans = conn.execute(
        "SELECT COUNT(*) FROM ci_name_tokens t WHERE t.kind = 1 "
        "AND NOT EXISTS (SELECT 1 FROM ci_symbols s WHERE s.id = t.row_id)"
    ).fetchone()[0]
    assert orphans == 0


def test_rebuild_is_idempotent(project):
    root, conn = project
    _populate(conn, CORPUS)
    rebuild_name_tokens(conn, root)
    first = conn.execute("SELECT COUNT(*) FROM ci_name_tokens").fetchone()[0]
    rebuild_name_tokens(conn, root)
    assert conn.execute("SELECT COUNT(*) FROM ci_name_tokens").fetchone()[0] == first


def test_project_stopwords_are_stable_across_calls(project):
    """They are baked into the stored postings, so drift would silently change
    what the index means."""
    root, _conn = project
    assert project_stopwords(root) == project_stopwords(Path(str(root)))
    assert "myproj" in project_stopwords(root)
