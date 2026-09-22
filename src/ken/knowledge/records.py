"""Validate and persist justifications alongside Ken's existing findings."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from .dependencies import Fingerprints, assess, capture


def prepare(data: dict[str, Any], root: Path | None) -> dict[str, Any]:
    fields = {"kind", "rationale", "evidence", "dependencies", "assumptions", "recheck", "check_runs"}
    if not isinstance(data, dict) or set(data) - fields:
        raise ValueError(
            "justification fields: kind, rationale, evidence, dependencies, assumptions, recheck, check_runs"
        )
    kind = data.get("kind", "observation")
    if not isinstance(kind, str) or kind not in {
        "observation",
        "decision",
        "hypothesis",
        "derivation",
    }:
        raise ValueError("unsupported justification kind")
    rationale = _text(data.get("rationale"), "rationale", 4000)
    recheck = _text(data.get("recheck", ""), "recheck", 1000, empty=True)
    assumptions = data.get("assumptions", [])
    if not isinstance(assumptions, list) or len(assumptions) > 16:
        raise ValueError("assumptions must be a list of at most 16 strings")
    assumptions = [_text(x, "assumption", 500) for x in assumptions]
    check_runs = data.get("check_runs", [])
    if not isinstance(check_runs, list) or len(check_runs) > 8 or any(not isinstance(r, str) for r in check_runs):
        raise ValueError("check_runs must contain at most eight receipt IDs")
    evidence = list(data.get("evidence", [])) if isinstance(data.get("evidence", []), list) else data.get("evidence")
    if check_runs:
        if root is None:
            raise ValueError("check receipts require a project root")
        from ken.checks.integration import freshness
        from ken.checks.store import Store
        store = Store(root)
        if not isinstance(evidence, list):
            raise ValueError("evidence must be a list")
        for run_id in dict.fromkeys(check_runs):
            receipt = store.read("runs", run_id)
            if freshness(root, receipt, seconds=2.0)["state"] != "unchanged":
                raise ValueError("check inputs changed before recording; rerun ken_check")
            evidence.append({"path": store.path("runs", run_id).relative_to(root.resolve()).as_posix(),
                             "note": "Immutable KQL2 check receipt; retain status, scope and uncertainty."})
    specs = data.get("dependencies", [])
    if not isinstance(evidence, list) or len(evidence) > 16:
        raise ValueError("evidence must be a list of at most 16 file references")
    if not isinstance(specs, list) or len(specs) > 32:
        raise ValueError(
            "dependencies must be a list of at most 32 file/tree references"
        )
    specs = list(specs)
    clean_evidence = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) - {"path", "note", "sha256"}:
            raise ValueError("evidence fields: path, note, sha256")
        path = _text(item.get("path"), "evidence path", 1000)
        note = _text(item.get("note", ""), "evidence note", 1000, empty=True)
        spec = {"kind": "file", "path": path}
        if "sha256" in item:
            spec["sha256"] = item["sha256"]
        specs.append(spec)
        clean_evidence.append({"path": path, "note": note})
    if specs and root is None:
        raise ValueError("a project root is required to capture dependencies")
    dependencies = capture(specs, root) if root is not None else []
    result = {
        "version": 1,
        "kind": kind,
        "rationale": rationale,
        "evidence": clean_evidence,
        "dependencies": dependencies,
        "assumptions": assumptions,
        "recheck": recheck,
    }
    if check_runs:
        result["check_runs"] = list(dict.fromkeys(check_runs))
    return result


def _text(value: Any, field: str, limit: int, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value.strip())
    ):
        raise ValueError(f"{field} must be {'0' if empty else '1'}..{limit} characters")
    return value.strip()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS cr_justifications (
        finding_id INTEGER PRIMARY KEY REFERENCES cr_findings(id) ON DELETE CASCADE,
        payload TEXT NOT NULL
    )""")


def save(
    conn: sqlite3.Connection, finding_id: int, data: dict[str, Any] | None
) -> None:
    # Called in the finding's transaction. A plain overwrite removes the old
    # justification: it cannot silently endorse a new conclusion.
    conn.execute("DELETE FROM cr_justifications WHERE finding_id = ?", (finding_id,))
    if data is not None:
        conn.execute(
            "INSERT INTO cr_justifications VALUES (?, ?)",
            (finding_id, json.dumps(data, ensure_ascii=False)),
        )


def project_root(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            database = Path(row[2])
            if database.parent.name == ".ken":
                return database.parent.parent
    return None


def enrich(
    conn: sqlite3.Connection, hits: list[dict], *, root: Path | None = None
) -> list[dict]:
    """Attach live validity to selected notes, without loading proof artifacts."""
    if not hits:
        return hits
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name='cr_justifications'"
    ).fetchone()
    if not exists:
        return hits
    root = root or project_root(conn)
    fingerprints = Fingerprints(root) if root is not None else None
    out = []
    for hit in hits:
        row = conn.execute(
            """SELECT j.payload, f.content FROM cr_justifications j
            JOIN cr_findings f ON f.id=j.finding_id WHERE f.topic=?""",
            (hit["topic"],),
        ).fetchone()
        if row is None:
            out.append(hit)
            continue
        try:
            data = json.loads(row["payload"])
            if data["version"] != 1:
                raise ValueError("unsupported justification version")
            validity = assess(data["dependencies"], fingerprints)
            if data.get("check_runs"):
                from ken.checks.integration import freshness
                from ken.checks.store import Store
                if root is None:
                    raise ValueError("project root unavailable for check receipt")
                checks = []
                states = [validity["state"]]
                issues = list(validity.get("issues", []))
                for run_id in data["check_runs"]:
                    receipt = Store(root).read("runs", run_id)
                    live = freshness(root, receipt)
                    states.append(live["state"])
                    issues.extend(live.get("issues", []))
                    checks.append({"run_id": run_id, "status": receipt["status"],
                                   "rules": [o["rule"] for o in receipt["checks"]], "validity": live["state"],
                                   "observations": live["checks"]})
                validity = {"state": "stale" if "stale" in states else "unknown" if "unknown" in states else "unchanged",
                            "issues": issues, "checks": checks,
                            "scope": "Declared inputs; no KQL replay or verification of memory prose."}
        except (ValueError, KeyError, TypeError, OSError):
            data = {}
            validity = {"state": "unknown", "issues": ["invalid justification record"]}
        out.append(
            hit
            | {"content": row["content"], "justification": data, "validity": validity}
        )
    return out


def for_topics(
    conn: sqlite3.Connection, topics: list[str], *, root: Path | None = None
) -> list[dict]:
    hits = []
    for topic in dict.fromkeys(topics):
        row = conn.execute(
            "SELECT topic, content FROM cr_findings WHERE topic=?", (topic,)
        ).fetchone()
        if row is not None:
            hits.append(dict(row))
    return enrich(conn, hits, root=root)
