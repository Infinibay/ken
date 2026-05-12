"""Post-merge boosts: freshness multiplier, cooc additive, dismissal penalty."""

from __future__ import annotations

import pytest

from ken.ranker import RankedItem
from ken.ranker.boosts import (
    COOC_ANCHOR_MIN_SCORE,
    COOC_MIN_PROPAGATED,
    COOC_MIN_SESSIONS,
    COOC_PROPAGATION,
    COOC_SATURATE_SESSIONS,
    DISMISS_PENALTY,
    FRESH_DECAY_DAYS,
    FRESH_MAX_MULT,
    apply_cooc,
    apply_dismissal_penalty,
    apply_freshness,
    apply_implementation_intent,
    apply_import_affinity,
    apply_language_intent,
    apply_symbol_file_affinity,
    apply_test_affinity,
)
from ken.ranker.channels import SimilarPrompt


def _file(target: str, score: float, reason: str = "") -> RankedItem:
    return RankedItem(target=target, target_type="file", score=score, reason=reason)


def _sym(target: str, score: float, reason: str = "") -> RankedItem:
    return RankedItem(target=target, target_type="symbol", score=score, reason=reason)


def test_implementation_intent_demotes_tests_when_prompt_asks_source_location():
    files = [
        _file("tests/test_memory.py", 2.0, "lexical"),
        _file("src/memory.py", 1.0, "symbol-file"),
    ]

    apply_implementation_intent(files, "where is anchored memory implemented")

    by_path = {item.target: item for item in files}
    assert by_path["tests/test_memory.py"].score == pytest.approx(0.9)
    assert by_path["src/memory.py"].score == pytest.approx(1.3)
    assert "impl-intent" in by_path["tests/test_memory.py"].reason
    assert "impl-intent" in by_path["src/memory.py"].reason


def test_implementation_intent_keeps_tests_when_prompt_mentions_tests():
    files = [
        _file("tests/test_memory.py", 2.0, "lexical"),
        _file("src/memory.py", 1.0, "symbol-file"),
    ]

    apply_implementation_intent(files, "which tests cover anchored memory")

    assert [item.score for item in files] == [2.0, 1.0]


def test_language_intent_boosts_named_parser_language_and_demotes_siblings():
    files = [
        _file("src/ken/parsers/typescript.py", 2.0, "lexical"),
        _file("src/ken/parsers/c.py", 2.0, "lexical"),
        _file("tests/parsers/test_typescript.py", 1.0, "lexical"),
        _file("tests/parsers/test_c.py", 1.0, "lexical"),
    ]
    symbols = [
        _sym("parse_ts_file (src/ken/parsers/typescript.py:21)", 2.0, "lexical"),
        _sym("test_c_parser_extracts_top_level_functions (tests/parsers/test_c.py:6)", 2.0, "lexical"),
    ]

    apply_language_intent(files, symbols, "parser extracts TypeScript class methods")

    by_path = {item.target: item for item in files}
    by_symbol = {item.target: item for item in symbols}
    assert by_path["src/ken/parsers/typescript.py"].score == pytest.approx(2.4)
    assert by_path["src/ken/parsers/c.py"].score == pytest.approx(1.1)
    assert by_path["tests/parsers/test_typescript.py"].score == pytest.approx(1.4)
    assert by_path["tests/parsers/test_c.py"].score == pytest.approx(0.55)
    assert by_symbol["parse_ts_file (src/ken/parsers/typescript.py:21)"].score == pytest.approx(2.3)
    assert by_symbol[
        "test_c_parser_extracts_top_level_functions (tests/parsers/test_c.py:6)"
    ].score == pytest.approx(1.1)


# ── apply_freshness ──────────────────────────────────────────────────


def test_freshness_recent_file_at_max(conn, make_file):
    make_file("src/a.py", days_old=0.0)
    files = [_file("src/a.py", 5.0)]
    apply_freshness(conn, files)
    assert files[0].score == pytest.approx(5.0 * FRESH_MAX_MULT)
    assert "fresh×" in files[0].reason


def test_freshness_decays_linearly(conn, make_file):
    """Half-decayed: a file 3.5d old gets ~halfway between 1.0 and FRESH_MAX_MULT."""
    make_file("src/a.py", days_old=FRESH_DECAY_DAYS / 2)
    files = [_file("src/a.py", 4.0)]
    apply_freshness(conn, files)
    expected_mult = 1.0 + (FRESH_MAX_MULT - 1.0) * 0.5
    assert files[0].score == pytest.approx(4.0 * expected_mult, rel=0.05)


def test_freshness_skips_old_files(conn, make_file):
    """Files older than FRESH_DECAY_DAYS get no boost."""
    make_file("src/a.py", days_old=FRESH_DECAY_DAYS + 1)
    files = [_file("src/a.py", 5.0)]
    apply_freshness(conn, files)
    assert files[0].score == 5.0  # unchanged
    assert "fresh×" not in files[0].reason


def test_freshness_skips_files_not_in_db(conn):
    """File ranked but not indexed → no boost, no crash."""
    files = [_file("src/ghost.py", 5.0)]
    apply_freshness(conn, files)
    assert files[0].score == 5.0


def test_freshness_empty_input_noop(conn):
    apply_freshness(conn, [])  # should not raise


# ── apply_cooc ────────────────────────────────────────────────────────


def _seed_session_score(
    conn, session_pk: int, target: str, score: float, *, pattern: str = "neutral", created_at: int = 0
) -> None:
    conn.execute(
        "INSERT INTO cr_session_scores(session_id, target_kind, target_path, score, pattern, created_at) "
        "VALUES (?, 'file', ?, ?, ?, ?)",
        (session_pk, target, score, pattern, created_at),
    )


def test_cooc_requires_anchor_above_threshold(conn, make_session):
    """Files below COOC_ANCHOR_MIN_SCORE don't act as anchors."""
    sess = make_session("past")
    _seed_session_score(conn, sess, "src/a.py", 5.0, created_at=999_999_999_999)
    _seed_session_score(conn, sess, "src/b.py", 5.0, created_at=999_999_999_999)
    # Only file in current rank, but its score is below the anchor cutoff.
    files = [_file("src/a.py", COOC_ANCHOR_MIN_SCORE - 0.1)]
    apply_cooc(conn, files)
    # No anchors → no propagation.
    assert all(it.target == "src/a.py" for it in files)
    assert len(files) == 1


def test_cooc_propagates_corroborated_files(conn, make_session):
    """Files cooccurring with anchor across ≥ COOC_MIN_SESSIONS sessions get a bonus."""
    import time
    now_ms = int(time.time() * 1000)
    # Need COOC_MIN_SESSIONS=2 sessions where anchor src/a.py was useful AND src/b.py shows up.
    for i in range(COOC_MIN_SESSIONS + 1):
        sess = make_session(f"past-{i}")
        _seed_session_score(conn, sess, "src/a.py", 5.0, created_at=now_ms)
        _seed_session_score(conn, sess, "src/b.py", 3.0, created_at=now_ms)
    files = [_file("src/a.py", 5.0)]
    apply_cooc(conn, files)
    by_target = {it.target: it for it in files}
    # b should have been added with a cooc contribution.
    assert "src/b.py" in by_target
    assert by_target["src/b.py"].score >= COOC_MIN_PROPAGATED
    assert "cooc" in by_target["src/b.py"].reason


def test_cooc_saturates_at_max_sessions(conn, make_session):
    """Beyond COOC_SATURATE_SESSIONS, more sessions don't grow the bonus."""
    import time
    now_ms = int(time.time() * 1000)
    # Build with exactly SATURATE sessions vs SATURATE+5 sessions.
    def _build(n):
        for i in range(n):
            sess = make_session(f"sat-{i}")
            _seed_session_score(conn, sess, "src/anchor.py", 5.0, created_at=now_ms)
            _seed_session_score(conn, sess, "src/b.py", 3.0, created_at=now_ms)

    _build(COOC_SATURATE_SESSIONS)
    files1 = [_file("src/anchor.py", 5.0)]
    apply_cooc(conn, files1)
    score1 = next(it.score for it in files1 if it.target == "src/b.py")

    # Reset DB by truncating relevant tables; easier to start a fresh conn fixture.
    conn.execute("DELETE FROM cr_session_scores")
    conn.execute("DELETE FROM cr_sessions")
    _build(COOC_SATURATE_SESSIONS + 5)
    files2 = [_file("src/anchor.py", 5.0)]
    apply_cooc(conn, files2)
    score2 = next(it.score for it in files2 if it.target == "src/b.py")

    assert score2 == pytest.approx(score1)


def test_cooc_skips_below_minimum_propagated(conn, make_session):
    """If contribution < COOC_MIN_PROPAGATED, nothing gets added."""
    import time
    now_ms = int(time.time() * 1000)
    # Anchor at exactly threshold (score=0.6), 2 sessions → contribution
    # = 0.6 * 0.4 * (2/5) = 0.096, well below the 0.3 minimum.
    for i in range(2):
        sess = make_session(f"weak-{i}")
        _seed_session_score(conn, sess, "src/a.py", COOC_ANCHOR_MIN_SCORE, created_at=now_ms)
        _seed_session_score(conn, sess, "src/b.py", 0.5, created_at=now_ms)
    files = [_file("src/a.py", COOC_ANCHOR_MIN_SCORE)]
    apply_cooc(conn, files)
    assert all(it.target != "src/b.py" for it in files)


def test_cooc_empty_files_noop(conn):
    apply_cooc(conn, [])  # no crash


def test_cooc_boosts_existing_in_place(conn, make_session):
    """If the cooc target is already in *files*, score is added not replaced."""
    import time
    now_ms = int(time.time() * 1000)
    for i in range(3):
        sess = make_session(f"past-{i}")
        _seed_session_score(conn, sess, "src/a.py", 5.0, created_at=now_ms)
        _seed_session_score(conn, sess, "src/b.py", 4.0, created_at=now_ms)
    # b's current score is below the anchor threshold so it stays a target,
    # not an anchor — the boost should add to its existing score in place.
    files = [_file("src/a.py", 5.0), _file("src/b.py", 0.4)]
    apply_cooc(conn, files)
    by_t = {it.target: it for it in files}
    # b stayed in *files* (not duplicated) and grew.
    assert sum(1 for it in files if it.target == "src/b.py") == 1
    assert by_t["src/b.py"].score > 0.4


# ── apply_dismissal_penalty ─────────────────────────────────────────


def test_dismissal_subtracts_penalty(conn, make_session, make_interaction):
    sess = make_session("past")
    make_interaction(sess, event="dismissed", target="src/a.py", iteration=1)
    files = [_file("src/a.py", 5.0)]
    similar = [SimilarPrompt(session_id=sess, sim=0.9, days_ago=0.0)]
    apply_dismissal_penalty(conn, files, similar)
    # n=1 → damp = DISMISS_PENALTY * 1/3
    expected = 5.0 - DISMISS_PENALTY * 1 / 3.0
    assert files[0].score == pytest.approx(expected)
    assert "-dismiss" in files[0].reason


def test_dismissal_saturates_at_three(conn, make_session, make_interaction):
    """3 dismissals across 3 sessions = max penalty; 5 doesn't grow it more."""
    similar = []
    for i in range(5):
        sess = make_session(f"past-{i}")
        make_interaction(sess, event="dismissed", target="src/a.py", iteration=1)
        similar.append(SimilarPrompt(session_id=sess, sim=0.9, days_ago=0.0))
    files = [_file("src/a.py", 5.0)]
    apply_dismissal_penalty(conn, files, similar)
    assert files[0].score == pytest.approx(5.0 - DISMISS_PENALTY)


def test_dismissal_floors_at_zero(conn, make_session, make_interaction):
    """Score never goes below 0 even if the penalty exceeds it."""
    similar = []
    for i in range(3):
        sess = make_session(f"past-{i}")
        make_interaction(sess, event="dismissed", target="src/a.py", iteration=1)
        similar.append(SimilarPrompt(session_id=sess, sim=0.9, days_ago=0.0))
    files = [_file("src/a.py", 0.5)]
    apply_dismissal_penalty(conn, files, similar)
    assert files[0].score == 0.0


def test_dismissal_empty_inputs_noop(conn):
    apply_dismissal_penalty(conn, [], [])  # no crash
    apply_dismissal_penalty(conn, [_file("a", 1.0)], [])  # no similar → noop


# ── apply_symbol_file_affinity ───────────────────────────────────────


def test_symbol_file_affinity_adds_containing_file_from_symbol_target(conn, make_file):
    make_file("src/ken/ranker/channels.py")
    symbols = [
        _sym(
            "lexical_scores (src/ken/ranker/channels.py:529)",
            3.0,
            "lexical:lexical",
        )
    ]
    files: list[RankedItem] = []

    apply_symbol_file_affinity(conn, files, symbols)

    by_target = {it.target: it for it in files}
    assert "src/ken/ranker/channels.py" in by_target
    assert by_target["src/ken/ranker/channels.py"].score > 0
    assert "symbol-file(" in by_target["src/ken/ranker/channels.py"].reason


def test_symbol_file_affinity_boosts_existing_containing_file(conn, make_file):
    make_file("src/ken/ranker/channels.py")
    files = [_file("src/ken/ranker/channels.py", 0.4, "lexical")]
    symbols = [_sym("lexical_scores (src/ken/ranker/channels.py:529)", 3.0)]

    apply_symbol_file_affinity(conn, files, symbols)

    assert len(files) == 1
    assert files[0].score > 0.4
    assert "symbol-file+" in files[0].reason


def test_symbol_file_affinity_counts_one_symbol_per_file(conn, make_file):
    make_file("src/ken/ranker/channels.py")
    files = [_file("src/ken/ranker/channels.py", 0.4, "lexical")]
    symbols = [
        _sym("lexical_scores (src/ken/ranker/channels.py:529)", 3.0),
        _sym("fuzzy_scores (src/ken/ranker/channels.py:219)", 2.5),
    ]

    apply_symbol_file_affinity(conn, files, symbols)

    assert len(files) == 1
    assert files[0].score == pytest.approx(0.4 + 3.0 * 0.35)
    assert files[0].reason.count("symbol-file+") == 1


def test_symbol_file_affinity_limits_by_distinct_files(conn, make_file):
    make_file("tests/ranker/test_rank.py")
    make_file("tests/ranker/test_boosts.py")
    symbols = [
        _sym(f"test_rank_{idx} (tests/ranker/test_rank.py:{idx})", 3.0 - idx * 0.01)
        for idx in range(10, 15)
    ]
    symbols.append(_sym("test_test_affinity (tests/ranker/test_boosts.py:20)", 1.8))
    files: list[RankedItem] = []

    apply_symbol_file_affinity(conn, files, symbols)

    by_target = {it.target: it for it in files}
    assert "tests/ranker/test_rank.py" in by_target
    assert "tests/ranker/test_boosts.py" in by_target


def test_symbol_file_affinity_ignores_weak_symbols(conn, make_file):
    make_file("src/ken/ranker/channels.py")
    files: list[RankedItem] = []
    symbols = [_sym("lexical_scores (src/ken/ranker/channels.py:529)", 0.5)]

    apply_symbol_file_affinity(conn, files, symbols)

    assert files == []


# ── apply_test_affinity ─────────────────────────────────────────────


def test_test_affinity_adds_matching_test_file(conn, make_file):
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    files = [_file("src/ken/status.py", 4.0, "fuzzy")]
    apply_test_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert "tests/test_status.py" in by_target
    assert by_target["tests/test_status.py"].score > 0
    assert "test-affinity(src/ken/status.py)" in by_target["tests/test_status.py"].reason


def test_test_affinity_boosts_existing_test_file(conn, make_file):
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    files = [_file("src/ken/status.py", 4.0), _file("tests/test_status.py", 0.2, "fuzzy")]
    apply_test_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert sum(1 for it in files if it.target == "tests/test_status.py") == 1
    assert by_target["tests/test_status.py"].score > 0.2
    assert "test-affinity+" in by_target["tests/test_status.py"].reason


def test_test_affinity_adds_source_file_from_test_anchor(conn, make_file):
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    files = [_file("tests/test_status.py", 4.0, "explicit-mention")]
    apply_test_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert "src/ken/status.py" in by_target
    assert by_target["src/ken/status.py"].score >= 1.0
    assert "test-affinity(tests/test_status.py)" in by_target["src/ken/status.py"].reason


def test_test_affinity_boosts_existing_source_file_from_test_anchor(conn, make_file):
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    files = [_file("tests/test_status.py", 4.0), _file("src/ken/status.py", 0.2, "fuzzy")]
    apply_test_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert sum(1 for it in files if it.target == "src/ken/status.py") == 1
    assert by_target["src/ken/status.py"].score > 0.2
    assert "test-affinity+" in by_target["src/ken/status.py"].reason


def test_test_affinity_uses_highest_scoring_anchors(conn, make_file):
    for name in ("a", "b", "c", "d", "status"):
        make_file(f"src/ken/{name}.py")
        make_file(f"tests/test_{name}.py")
    files = [
        _file("tests/test_a.py", 1.1),
        _file("tests/test_b.py", 1.1),
        _file("tests/test_c.py", 1.1),
        _file("tests/test_d.py", 1.1),
        _file("tests/test_status.py", 3.0),
    ]

    apply_test_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert "src/ken/status.py" in by_target
    assert "test-affinity(tests/test_status.py)" in by_target["src/ken/status.py"].reason


def test_test_affinity_ignores_low_score_anchor(conn, make_file):
    make_file("src/ken/status.py")
    make_file("tests/test_status.py")

    files = [_file("src/ken/status.py", 0.1)]
    apply_test_affinity(conn, files)

    assert [it.target for it in files] == ["src/ken/status.py"]


# ── apply_import_affinity ───────────────────────────────────────────


def test_import_affinity_adds_direct_import_neighbor(conn, make_file):
    src_id = make_file("src/app.py")
    util_id = make_file("src/util.py")
    conn.execute(
        "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) VALUES (?, 'src.util', ?, 1)",
        (src_id, util_id),
    )

    files = [_file("src/app.py", 4.0, "fuzzy")]
    apply_import_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert "src/util.py" in by_target
    assert by_target["src/util.py"].score > 0
    assert "import-affinity(src/app.py)" in by_target["src/util.py"].reason


def test_import_affinity_adds_reverse_importer(conn, make_file):
    src_id = make_file("src/app.py")
    util_id = make_file("src/util.py")
    conn.execute(
        "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) VALUES (?, 'src.util', ?, 1)",
        (src_id, util_id),
    )

    files = [_file("src/util.py", 4.0, "fuzzy")]
    apply_import_affinity(conn, files)

    assert any(it.target == "src/app.py" for it in files)


def test_import_affinity_boosts_existing_neighbor(conn, make_file):
    src_id = make_file("src/app.py")
    util_id = make_file("src/util.py")
    conn.execute(
        "INSERT INTO ci_imports(from_file_id, to_module, to_file_id, line) VALUES (?, 'src.util', ?, 1)",
        (src_id, util_id),
    )

    files = [_file("src/app.py", 4.0), _file("src/util.py", 0.2, "lexical")]
    apply_import_affinity(conn, files)

    by_target = {it.target: it for it in files}
    assert sum(1 for it in files if it.target == "src/util.py") == 1
    assert by_target["src/util.py"].score > 0.2
    assert "import-affinity+" in by_target["src/util.py"].reason
