"""Post-processing boosts over merged file scores."""

from __future__ import annotations

import re
import sqlite3
import time

from ken.ranker import RankedItem
from ken.ranker.channels import SimilarPrompt

# ── Freshness ────────────────────────────────────────────────────────

FRESH_MAX_MULT = 1.3
FRESH_DECAY_DAYS = 7.0


def apply_freshness(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Multiplicative bump for files modified recently on disk.

    Linear decay from FRESH_MAX_MULT today to 1.0 at FRESH_DECAY_DAYS
    ago. Multiplicative *on top of* an existing score — this can't
    rescue an unranked file, only amplify one that already won.
    """
    if not files:
        return
    paths = [it.target for it in files]
    rows = conn.execute(
        f"SELECT path, mtime FROM ci_files WHERE path IN ({','.join('?' * len(paths))})",
        paths,
    ).fetchall()
    mtime_by_path: dict[str, int] = {r["path"]: int(r["mtime"]) for r in rows}
    now_ns = int(time.time() * 1e9)
    secs_per_day = 86_400
    for it in files:
        mtime_ns = mtime_by_path.get(it.target)
        if mtime_ns is None:
            continue
        days_ago = max(0.0, (now_ns - mtime_ns) / 1e9 / secs_per_day)
        if days_ago >= FRESH_DECAY_DAYS:
            continue
        mult = 1.0 + (FRESH_MAX_MULT - 1.0) * (1.0 - days_ago / FRESH_DECAY_DAYS)
        it.score *= mult
        it.reason = _append_reason(it.reason, f"fresh×{mult:.2f}")


# ── Co-occurrence ────────────────────────────────────────────────────

COOC_ANCHOR_MIN_SCORE = 0.6
COOC_MAX_ANCHORS = 5
COOC_MIN_SESSIONS = 2
COOC_PROPAGATION = 0.4
COOC_SATURATE_SESSIONS = 5
COOC_MIN_PROPAGATED = 0.3
COOC_LOOKBACK_DAYS = 90


def apply_cooc(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Boost files frequently accessed alongside the top anchors.

    For each anchor (file already scoring high), find other files that
    co-occurred in past sessions where the anchor was also useful.
    Saturating contribution by session count, with minimum 2 sessions
    of co-occurrence to count as signal.
    """
    if not files:
        return
    anchors = [it for it in files if it.score >= COOC_ANCHOR_MIN_SCORE][:COOC_MAX_ANCHORS]
    if not anchors:
        return
    anchor_paths = tuple(a.target for a in anchors)
    cutoff_ms = (int(time.time()) - COOC_LOOKBACK_DAYS * 86_400) * 1000

    # Sessions where one of the anchors was useful.
    placeholders = ",".join("?" * len(anchor_paths))
    rows = conn.execute(
        f"""
        SELECT DISTINCT session_id FROM cr_session_scores
        WHERE target_path IN ({placeholders})
          AND score >= ?
          AND created_at >= ?
        """,
        (*anchor_paths, COOC_ANCHOR_MIN_SCORE, cutoff_ms),
    ).fetchall()
    if not rows:
        return
    session_ids = tuple(int(r["session_id"]) for r in rows)
    sess_ph = ",".join("?" * len(session_ids))

    rows = conn.execute(
        f"""
        SELECT target_path, COUNT(DISTINCT session_id) AS sess, AVG(score) AS avg_score
        FROM cr_session_scores
        WHERE session_id IN ({sess_ph})
          AND target_path IS NOT NULL
          AND target_path NOT IN ({placeholders})
        GROUP BY target_path
        HAVING sess >= ?
        """,
        (*session_ids, *anchor_paths, COOC_MIN_SESSIONS),
    ).fetchall()

    by_path = {it.target: it for it in files}
    avg_anchor = sum(a.score for a in anchors) / len(anchors)
    for r in rows:
        path = r["target_path"]
        sess_count = int(r["sess"])
        contribution = (
            avg_anchor
            * COOC_PROPAGATION
            * min(sess_count / COOC_SATURATE_SESSIONS, 1.0)
        )
        if contribution < COOC_MIN_PROPAGATED:
            continue
        if path in by_path:
            by_path[path].score += contribution
            by_path[path].reason = _append_reason(by_path[path].reason, f"cooc+{contribution:.1f}")
        else:
            files.append(
                RankedItem(
                    target=path,
                    target_type="file",
                    score=contribution,
                    reason=f"cooc({sess_count}sess)",
                )
            )


# ── Dismissal penalty ────────────────────────────────────────────────
#
# When the user explicitly dismissed a file via `ken_dismiss` in a past
# session whose prompt was semantically close to the current one, knock
# its score down. Floors at zero — never negative, since merge already
# decided this file is in the running.
#
# Reads cr_interactions directly: a dismissed file's reactive score
# gets filtered out at score≤0, so the snapshot pipeline drops it; the
# raw event survives in cr_interactions for exactly this reason.

DISMISS_PENALTY = 1.5


def apply_dismissal_penalty(
    conn: sqlite3.Connection,
    files: list[RankedItem],
    similar: list[SimilarPrompt],
) -> None:
    if not files or not similar:
        return
    similar_session_ids = {sp.session_id for sp in similar}
    paths = [it.target for it in files]
    path_ph = ",".join("?" * len(paths))
    sess_ph = ",".join("?" * len(similar_session_ids))
    rows = conn.execute(
        f"""
        SELECT target_path, COUNT(DISTINCT session_id) AS n
        FROM cr_interactions
        WHERE event_type = 'dismissed'
          AND target_kind = 'file'
          AND target_path IN ({path_ph})
          AND session_id IN ({sess_ph})
        GROUP BY target_path
        """,
        (*paths, *similar_session_ids),
    ).fetchall()
    by_path = {it.target: it for it in files}
    for r in rows:
        n = int(r["n"])
        # Saturate the penalty at 3 dismissals — past that the user has
        # made themselves clear and we shouldn't compound the signal.
        damp = DISMISS_PENALTY * min(n, 3) / 3.0
        item = by_path[r["target_path"]]
        item.score = max(0.0, item.score - damp)
        item.reason = _append_reason(item.reason, f"-dismiss({damp:.1f})")


# ── Symbol-file affinity ────────────────────────────────────────────

SYMBOL_TARGET_RE = re.compile(r"^(?P<qualname>.+) \((?P<path>.+):(?P<line>\d+)\)$")
SYMBOL_FILE_AFFINITY_MIN_SYMBOL_SCORE = 1.8
SYMBOL_FILE_AFFINITY_MAX_SYMBOLS = 5
SYMBOL_FILE_AFFINITY_PROPAGATION = 0.35
SYMBOL_FILE_AFFINITY_MIN_SCORE = 0.7
SYMBOL_FILE_AFFINITY_MAX_SCORE = 2.0


def apply_symbol_file_affinity(
    conn: sqlite3.Connection, files: list[RankedItem], symbols: list[RankedItem]
) -> None:
    """Surface the containing file for high-confidence symbol hits.

    Fuzzy/lexical symbol search often identifies the exact function or
    class before the file embedding does. The agent still needs the file
    path to read or edit, so propagate a capped score from top symbols
    to their indexed files.
    """
    anchors = [
        it
        for it in sorted(symbols, reverse=True)
        if it.score >= SYMBOL_FILE_AFFINITY_MIN_SYMBOL_SCORE
    ][:SYMBOL_FILE_AFFINITY_MAX_SYMBOLS]
    if not anchors:
        return
    by_path = {it.target: it for it in files}
    for symbol in anchors:
        path = _symbol_file_path(conn, symbol.target)
        if path is None:
            continue
        contribution = min(
            SYMBOL_FILE_AFFINITY_MAX_SCORE,
            max(
                SYMBOL_FILE_AFFINITY_MIN_SCORE,
                symbol.score * SYMBOL_FILE_AFFINITY_PROPAGATION,
            ),
        )
        if path in by_path:
            by_path[path].score += contribution
            by_path[path].reason = _append_reason(
                by_path[path].reason, f"symbol-file+{contribution:.1f}"
            )
        else:
            item = RankedItem(
                target=path,
                target_type="file",
                score=contribution,
                reason=f"symbol-file({symbol.target})",
            )
            files.append(item)
            by_path[path] = item


def _symbol_file_path(conn: sqlite3.Connection, target: str) -> str | None:
    match = SYMBOL_TARGET_RE.match(target)
    if match:
        return match.group("path")
    row = conn.execute(
        """
        SELECT f.path
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE s.qualname = ? OR s.name = ?
        ORDER BY s.line_start
        LIMIT 1
        """,
        (target, target),
    ).fetchone()
    return None if row is None else str(row["path"])


# ── Test affinity ───────────────────────────────────────────────────

TEST_AFFINITY_ANCHOR_MIN_SCORE = 1.2
TEST_AFFINITY_MAX_ANCHORS = 5
TEST_AFFINITY_PROPAGATION = 0.35
TEST_AFFINITY_MIN_SCORE = 0.5


def apply_test_affinity(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Surface obvious source/test counterparts for high-scoring anchors.

    This is deliberately name-based and conservative. It rescues files
    such as ``tests/test_status.py`` when ``src/ken/status.py`` is
    already likely relevant, and ``src/ken/status.py`` when the ranked
    anchor is ``tests/test_status.py``, without trying to infer arbitrary
    coverage.
    """
    anchors = [
        it
        for it in files
        if it.score >= TEST_AFFINITY_ANCHOR_MIN_SCORE
    ][:TEST_AFFINITY_MAX_ANCHORS]
    if not anchors:
        return
    rows = conn.execute("SELECT path FROM ci_files").fetchall()
    all_paths = [r["path"] for r in rows]
    by_path = {it.target: it for it in files}

    for anchor in anchors:
        related = (
            _related_source_files(anchor.target, all_paths)
            if _is_test_path(anchor.target)
            else _related_tests(anchor.target, all_paths)
        )
        if not related:
            continue
        contribution = max(
            TEST_AFFINITY_MIN_SCORE,
            anchor.score * TEST_AFFINITY_PROPAGATION,
        )
        for path in related:
            if path in by_path:
                by_path[path].score += contribution
                by_path[path].reason = _append_reason(
                    by_path[path].reason, f"test-affinity+{contribution:.1f}"
                )
            else:
                item = RankedItem(
                    target=path,
                    target_type="file",
                    score=contribution,
                    reason=f"test-affinity({anchor.target})",
                )
                files.append(item)
                by_path[path] = item


def _related_tests(source_path: str, all_paths: list[str]) -> list[str]:
    stem = source_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if not stem or stem.startswith("test_"):
        return []
    candidates = {
        f"test_{stem}.py",
        f"{stem}_test.py",
        f"{stem}.test.py",
        f"test_{stem}.ts",
        f"{stem}.test.ts",
        f"{stem}.spec.ts",
        f"test_{stem}.js",
        f"{stem}.test.js",
        f"{stem}.spec.js",
    }
    out: list[str] = []
    for path in all_paths:
        name = path.rsplit("/", 1)[-1]
        if name in candidates or (
            _is_test_path(path) and stem.lower() in name.lower()
        ):
            out.append(path)
    return sorted(set(out))


def _related_source_files(test_path: str, all_paths: list[str]) -> list[str]:
    stem = _source_stem_from_test(test_path)
    if not stem:
        return []
    candidates = {
        f"{stem}.py",
        f"{stem}.pyi",
        f"{stem}.ts",
        f"{stem}.tsx",
        f"{stem}.js",
        f"{stem}.jsx",
        f"{stem}.go",
        f"{stem}.rs",
        f"{stem}.java",
    }
    out: list[str] = []
    for path in all_paths:
        if _is_test_path(path):
            continue
        name = path.rsplit("/", 1)[-1]
        if name in candidates:
            out.append(path)
    return sorted(set(out))


def _source_stem_from_test(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    for suffix in (".test", ".spec", "_test"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem.startswith("test_"):
        stem = stem[5:]
    return stem


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return (
        "/test/" in lower
        or "/tests/" in lower
        or lower.startswith("test/")
        or lower.startswith("tests/")
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


# ── Import affinity ─────────────────────────────────────────────────

IMPORT_AFFINITY_ANCHOR_MIN_SCORE = 1.2
IMPORT_AFFINITY_MAX_ANCHORS = 5
IMPORT_AFFINITY_PROPAGATION = 0.25
IMPORT_AFFINITY_MIN_SCORE = 0.4
IMPORT_AFFINITY_HUB_DEGREE = 8
IMPORT_AFFINITY_HUB_MIN_MULT = 0.35


def apply_import_affinity(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Surface direct import neighbours for high-scoring anchors."""
    anchors = [it for it in files if it.score >= IMPORT_AFFINITY_ANCHOR_MIN_SCORE][
        :IMPORT_AFFINITY_MAX_ANCHORS
    ]
    if not anchors:
        return
    anchor_paths = [a.target for a in anchors]
    placeholders = ",".join("?" * len(anchor_paths))
    rows = conn.execute(
        f"""
        SELECT src.path AS source_path, dst.path AS target_path
        FROM ci_imports i
        JOIN ci_files src ON src.id = i.from_file_id
        JOIN ci_files dst ON dst.id = i.to_file_id
        WHERE src.path IN ({placeholders}) OR dst.path IN ({placeholders})
        """,
        (*anchor_paths, *anchor_paths),
    ).fetchall()
    if not rows:
        return
    by_path = {it.target: it for it in files}
    anchor_score = {it.target: it.score for it in anchors}
    degrees = _import_degrees(conn)
    for row in rows:
        src = row["source_path"]
        dst = row["target_path"]
        if src in anchor_score:
            _apply_import_neighbor(files, by_path, dst, src, anchor_score[src], degrees)
        if dst in anchor_score:
            _apply_import_neighbor(files, by_path, src, dst, anchor_score[dst], degrees)


def _apply_import_neighbor(
    files: list[RankedItem],
    by_path: dict[str, RankedItem],
    path: str,
    anchor: str,
    anchor_score: float,
    degrees: dict[str, int],
) -> None:
    if path == anchor:
        return
    base = max(IMPORT_AFFINITY_MIN_SCORE, anchor_score * IMPORT_AFFINITY_PROPAGATION)
    hub_mult = _import_hub_multiplier(degrees.get(path, 0))
    contribution = base * hub_mult
    suffix = "" if hub_mult >= 1.0 else f";hub×{hub_mult:.2f}"
    if path in by_path:
        by_path[path].score += contribution
        by_path[path].reason = _append_reason(
            by_path[path].reason, f"import-affinity+{contribution:.1f}{suffix}"
        )
    else:
        item = RankedItem(
            target=path,
            target_type="file",
            score=contribution,
            reason=f"import-affinity({anchor}{suffix})",
        )
        files.append(item)
        by_path[path] = item


def _import_degrees(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT f.path AS path, COUNT(i.id) AS degree
        FROM ci_files f
        LEFT JOIN ci_imports i ON i.from_file_id = f.id OR i.to_file_id = f.id
        GROUP BY f.id, f.path
        """
    ).fetchall()
    return {str(r["path"]): int(r["degree"]) for r in rows}


def _import_hub_multiplier(degree: int) -> float:
    if degree <= IMPORT_AFFINITY_HUB_DEGREE:
        return 1.0
    return max(IMPORT_AFFINITY_HUB_MIN_MULT, IMPORT_AFFINITY_HUB_DEGREE / degree)


# ── Helpers ──────────────────────────────────────────────────────────


def _append_reason(existing: str, more: str) -> str:
    if not existing:
        return more
    return f"{existing} + {more}"
