"""Project health report for ken's index, memory, and daemon state."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ken import _paths
from ken.db import connect


@dataclass(frozen=True)
class StatusCounts:
    files: int
    files_embedded: int
    symbols: int
    symbols_embedded: int
    sessions: int
    active_sessions: int
    contexts: int
    prompt_contexts: int
    prompt_contexts_embedded: int
    interactions: int
    session_scores: int
    findings: int
    findings_embedded: int
    intent_sources: int
    intent_sources_embedded: int


def show_status(start: Path, *, as_json: bool = False) -> int:
    report = status_report(start)
    if not report["ok"]:
        if as_json:
            print(json.dumps(report, indent=2))
        else:
            print(report["error"], file=sys.stderr)
            print("hint: `ken install .` from a project root", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(report, indent=2))
        return 0
    _print_report(report)
    return 0


def status_report(start: Path) -> dict:
    """Return a JSON-serialisable status report for humans and agents."""
    root = _paths.find_project_root(start.resolve())
    if root is None:
        return {
            "ok": False,
            "error": f"no ken project found at or above {start.resolve()}",
        }

    meta = json.loads(_paths.meta_path(root).read_text(encoding="utf-8"))
    db_p = _paths.db_path(root)
    base = {
        "ok": True,
        "project_root": str(root),
        "project_id": meta["project_id"],
        "db": {
            "path": str(db_p),
            "size": _human_size(db_p),
            "exists": db_p.is_file(),
        },
    }

    if not db_p.is_file():
        return {**base, "installed": False}

    counts = _read_counts(db_p)
    index_health = _index_health(root, db_p)
    return {
        **base,
        "installed": True,
        "counts": counts.__dict__,
        "index_health": index_health,
        "rank_signals": _rank_signals(counts),
        "embedding_coverage": _embedding_coverage(counts),
        "recommendations": _recommendations(counts, index_health),
        "daemon": _daemon_health(root),
    }


def _print_report(report: dict) -> None:
    print(f"project_root  : {report['project_root']}")
    print(f"project_id    : {report['project_id']}")
    print(f"db            : {report['db']['path']}  ({report['db']['size']})")
    if not report.get("installed"):
        print("(no DB yet — run `ken install .`)")
        return
    counts = report["counts"]
    print(f"files indexed : {counts['files']} ({counts['files_embedded']} embedded)")
    print(f"symbols       : {counts['symbols']} ({counts['symbols_embedded']} embedded)")
    print(
        f"sessions      : {counts['sessions']} total, {counts['active_sessions']} active, "
        f"{counts['session_scores']} scored"
    )
    print(
        f"contexts      : {counts['contexts']} "
        f"({counts['prompt_contexts']} prompts, {counts['prompt_contexts_embedded']} embedded)"
    )
    print(f"interactions  : {counts['interactions']}")
    print(f"findings      : {counts['findings']} ({counts['findings_embedded']} embedded)")
    print(
        f"doc intents   : {counts['intent_sources']} "
        f"({counts['intent_sources_embedded']} embedded)"
    )
    index_health = report.get("index_health")
    if index_health and index_health["stale_files"]:
        sample = ", ".join(index_health["sample"])
        suffix = f" ({sample})" if sample else ""
        print(f"index health  : {index_health['stale_files']} stale files{suffix}")
    print(f"rank signals  : {_rank_signal_summary_from_dict(report['rank_signals'])}")
    coverage = report.get("embedding_coverage")
    if coverage and coverage["total"] > 0:
        print(
            "embedding cov : "
            f"{coverage['embedded']}/{coverage['total']} "
            f"({coverage['percent']:.1f}%)"
        )
    for rec in report.get("recommendations", []):
        print(f"recommendation: {rec}")
    daemon = report["daemon"]
    if not daemon["running"]:
        print("daemon        : stopped")
    else:
        print(
            "daemon        : running "
            f"(sessions={daemon.get('sessions_active', 0)}, idle={daemon.get('idle_s', '?')}s)"
        )


def _read_counts(db_p: Path) -> StatusCounts:
    conn = connect(db_p)
    try:
        return StatusCounts(
            files=_count(conn, "ci_files"),
            files_embedded=_count(conn, "ci_files", "embedding IS NOT NULL OR vec_slot IS NOT NULL"),
            symbols=_count(conn, "ci_symbols"),
            symbols_embedded=_count(conn, "ci_symbols", "embedding IS NOT NULL OR vec_slot IS NOT NULL"),
            sessions=_count(conn, "cr_sessions"),
            active_sessions=_count(conn, "cr_sessions", "ended_at IS NULL"),
            contexts=_count(conn, "cr_contexts"),
            prompt_contexts=_count(conn, "cr_contexts", "kind = 'user_prompt'"),
            prompt_contexts_embedded=_count(
                conn, "cr_contexts", "kind = 'user_prompt' AND embedding IS NOT NULL"
            ),
            interactions=_count(conn, "cr_interactions"),
            session_scores=_count(conn, "cr_session_scores"),
            findings=_count(conn, "cr_findings"),
            findings_embedded=_count(conn, "cr_findings", "embedding IS NOT NULL"),
            intent_sources=_count(conn, "ci_intent_sources"),
            intent_sources_embedded=_count(
                conn, "ci_intent_sources", "embedding IS NOT NULL OR vec_slot IS NOT NULL"
            ),
        )
    finally:
        conn.close()


def _count(conn, table: str, where: str | None = None) -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql).fetchone()["n"])


def _index_health(root: Path, db_p: Path) -> dict[str, int | list[str]]:
    conn = connect(db_p)
    try:
        rows = conn.execute("SELECT path FROM ci_files ORDER BY path").fetchall()
    finally:
        conn.close()

    stale: list[str] = []
    for row in rows:
        rel = row["path"]
        if not (root / rel).exists():
            stale.append(rel)
    return {"stale_files": len(stale), "sample": stale[:5]}


def _daemon_health(root: Path) -> dict:
    from ken.daemon import client as daemon_client

    health = daemon_client.health(root)
    if not health:
        return {"running": False}
    return {"running": True, **health}


def _rank_signal_summary(counts: StatusCounts) -> str:
    return _rank_signal_summary_from_dict(_rank_signals(counts))


def _rank_signals(counts: StatusCounts) -> dict[str, str]:
    if counts.files == 0:
        index = "index=empty"
    else:
        index = "index=yes"
    if counts.files == 0 and counts.symbols == 0:
        embeddings = "embeddings=none"
    else:
        embedded = counts.files_embedded + counts.symbols_embedded
        total = counts.files + counts.symbols
        if embedded == 0:
            embeddings = "embeddings=none"
        elif embedded == total:
            embeddings = "embeddings=ready"
        else:
            embeddings = f"embeddings=partial({embedded}/{total})"
    predictive = (
        "predictive=yes"
        if counts.session_scores and counts.prompt_contexts_embedded
        else "predictive=no"
    )
    findings = "findings=yes" if counts.findings_embedded else "findings=no"
    return {
        "index": index.split("=", 1)[1],
        "embeddings": embeddings.split("=", 1)[1],
        "predictive": predictive.split("=", 1)[1],
        "findings": findings.split("=", 1)[1],
    }


def _embedding_coverage(counts: StatusCounts) -> dict[str, int | float]:
    embedded = counts.files_embedded + counts.symbols_embedded
    total = counts.files + counts.symbols
    percent = (embedded / total * 100.0) if total else 0.0
    return {"embedded": embedded, "total": total, "percent": round(percent, 1)}


def _rank_signal_summary_from_dict(signals: dict[str, str]) -> str:
    return (
        f"index={signals['index']}, "
        f"embeddings={signals['embeddings']}, "
        f"predictive={signals['predictive']}, "
        f"findings={signals['findings']}"
    )


def _recommendations(
    counts: StatusCounts,
    index_health: dict[str, int | list[str]] | None = None,
) -> list[str]:
    recs: list[str] = []
    embedded = counts.files_embedded + counts.symbols_embedded
    total = counts.files + counts.symbols
    if counts.files == 0:
        recs.append("run `ken install .` or re-run it to populate the code index")
    elif index_health and index_health.get("stale_files"):
        recs.append(
            "indexed files are missing on disk; run `ken install .` "
            "to resync after branch changes"
        )
    if counts.files and embedded == 0:
        recs.append("run `ken rank \"your task\"` once to lazily build embeddings")
    elif counts.files and embedded < total:
        recs.append(
            "embeddings are partial; use `ken install . --embed --embed-limit N` "
            "to warm more of the project when semantic recall matters"
        )
    if counts.prompt_contexts_embedded == 0:
        recs.append("submit at least one prompt through a hooked agent to seed context history")
    elif counts.interactions == 0:
        recs.append("verify tool hooks are recording reads/edits; no interactions have been captured")
    if counts.session_scores == 0:
        if counts.active_sessions:
            recs.append("end the active session to snapshot predictive scores")
        else:
            recs.append("let hooks run through a few real turns to build predictive history")
    if counts.findings_embedded == 0:
        recs.append("save reusable project facts with `ken remember TOPIC CONTENT`")
    return recs


def _human_size(p: Path) -> str:
    if not p.is_file():
        return "missing"
    size = p.stat().st_size
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TiB"
