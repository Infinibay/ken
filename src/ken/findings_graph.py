"""A deterministic relationship graph over ``cr_findings``.

ken's findings (saved by ``ken_remember``) are otherwise a flat list of
isolated notes. This module links them into a graph so accumulated
knowledge can be navigated: which notes touch the same code, say related
things, or share tags. Two tables carry it (see ``schema.sql``):

* **``cr_finding_refs``** — the finding → code *bridge*. Each finding's
  prose is scanned for file paths and code identifiers, which are resolved
  against ``ci_files`` / ``ci_symbols``. Grouping happens on the durable
  ``ref_key`` text (a path, or ``qualname\\x1fpath``), never the churny
  ``ci_symbols.id``. This lets a note mentioning ``src/ken/cochange.py``
  reach that file's importers, tests, and co-change partners.
* **``cr_finding_edges``** — typed, evidence-carrying finding ↔ finding
  edges (``semantic`` | ``shared_file`` | ``shared_symbol`` | ``shared_tag``).
  Never a fused black-box score — each edge names *why* it exists, mirroring
  ``blast_radius`` / ``cochange``.

Design choices that keep it honest and cheap:

* **Full recompute on write.** Findings number in the tens–low-hundreds, so
  the whole finding↔finding edge set is rebuilt on each ``remember`` /
  ``forget`` (~ms). This sidesteps the correctness traps of incremental kNN
  maintenance (a mutual-kNN edge is non-local; global IDF drifts on every
  write). Refs are re-extracted only for the changed finding.
* **Never fails a write.** All graph work runs inside a ``SAVEPOINT`` in the
  caller's transaction; on any error it is rolled back and the user's finding
  is still committed (see ``memory.remember`` / ``memory.forget``).
* **Deterministic.** Identical DB → identical graph: canonical ``(min,max)``
  edge storage, sorted iteration, weights rounded to 4 dp to absorb BLAS drift.

Embedder-free: edges read the embeddings already stored on ``cr_findings``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import defaultdict
from itertools import combinations

import numpy as np

from ken.db import get_meta, set_meta
from ken.embedder import blob_to_vec

# ── Version / kill-switch ────────────────────────────────────────────
# Bump to force a full rebuild (backfill) on the next ensure_finding_graph.
FINDINGS_GRAPH_VERSION = 1
_META_VERSION = "findings_graph_version"
_META_ENABLED = "findings_graph_enabled"
_META_NOTE = "findings_graph_note"

# ── Edge tuning (conservative defaults; calibrate against a real corpus) ──
SIM_THRESHOLD = 0.60          # semantic-edge cosine floor (above the 0.48 rank gate)
N_MIN = 8                     # below this, skip IDF/hub weighting (they misbehave tiny)
K_SYM = 5                     # drop identifier tokens resolving to > K_SYM symbols
N_SEMANTIC_CAP = 2000         # skip O(N^2) semantic pairing above this many findings
_EVIDENCE_NODE_CAP = 8        # max keys/tags listed in an edge's evidence JSON

EDGE_SEMANTIC = "semantic"
EDGE_SHARED_FILE = "shared_file"
EDGE_SHARED_SYMBOL = "shared_symbol"
EDGE_SHARED_TAG = "shared_tag"
_EXACT_EDGE_TYPES = (EDGE_SHARED_FILE, EDGE_SHARED_SYMBOL, EDGE_SHARED_TAG)

# ── Read-tool defaults ───────────────────────────────────────────────
DEFAULT_RELATED_LIMIT = 8
DEFAULT_RELATED_MIN_WEIGHT = 0.3
DEFAULT_FILE_FINDINGS_LIMIT = 15
_EXPAND_MIN_WEIGHT = 0.4
_CONTENT_PREVIEW = 200

_KEY_SEP = "\x1f"  # qualname / path separator inside a symbol ref_key

# ── Extraction patterns (mirrors ranker.channels.explicit_mentions, but the
# resolution is language-agnostic: a path token counts if it matches an indexed
# ci_files.path, regardless of extension — channels' _KNOWN_EXTS omitted every
# language added in 0.2.0). ─────────────────────────────────────────────────
# Extension token allows digits and up to 8 chars so .ps1 / .graphql / .gemspec
# aren't silently dropped — resolution against ci_files.path is the real gate.
_PATH_RE = re.compile(r"\b[\w./\-]+\.[A-Za-z][A-Za-z0-9]{0,7}\b(?::\d+(?:-\d+)?)?")
_IDENT_RE = re.compile(r"`([^`\n]+)`|\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\b")
_SNAKE_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b")

# Extensions that make an *unresolved* token path-shaped enough to persist
# (resolved tokens bypass this — they matched a real ci_files.path).
_SOURCE_EXTS = frozenset(
    "py pyi js jsx ts tsx mjs cjs go rs java rb php kt kts dart cs cpp cc cxx "
    "c h hpp swift scala m mm sh sql html css ps1 psm1 psd1 graphql gql "
    "gemspec rake vue svelte lua ex exs erl gradle".split()
)

# Generic identifier names that collide across files — never bridge on them.
_SYMBOL_STOPLIST = frozenset(
    {
        "run", "main", "connect", "close", "setup", "init", "__init__",
        "__main__", "execute", "get", "set", "load", "save", "open", "read",
        "write", "start", "stop", "call", "send", "post", "handle", "build",
    }
)
# Prose words the CamelCase identifier regex catches (`The`, `This`, …).
_IDENT_STOPWORDS = frozenset(
    {
        "the", "this", "that", "these", "those", "when", "where", "which",
        "while", "with", "from", "into", "note", "todo", "then", "than",
        "here", "there", "true", "false", "none", "null", "and", "for",
    }
)
# Tags that carry no topical meaning — excluded before shared_tag Jaccard.
_TAG_STOPLIST = frozenset({"bug", "todo", "wip", "fixme", "note", "hack"})


# ── Table creation / lifecycle ───────────────────────────────────────

_CREATE_SQL = (
    """
    CREATE TABLE IF NOT EXISTS cr_finding_refs (
        finding_id  INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
        ref_kind    TEXT    NOT NULL,
        ref_key     TEXT    NOT NULL,
        file_id     INTEGER REFERENCES ci_files(id)   ON DELETE SET NULL,
        symbol_id   INTEGER REFERENCES ci_symbols(id) ON DELETE SET NULL,
        method      TEXT    NOT NULL,
        resolved    INTEGER NOT NULL DEFAULT 0,
        updated_at  INTEGER NOT NULL,
        PRIMARY KEY (finding_id, ref_kind, ref_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_key ON cr_finding_refs(ref_kind, ref_key)",
    "CREATE INDEX IF NOT EXISTS idx_cr_finding_refs_file ON cr_finding_refs(file_id) WHERE file_id IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS cr_finding_edges (
        src         INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
        dst         INTEGER NOT NULL REFERENCES cr_findings(id) ON DELETE CASCADE,
        edge_type   TEXT    NOT NULL,
        directed    INTEGER NOT NULL DEFAULT 0,
        weight      REAL    NOT NULL,
        evidence    TEXT    NOT NULL DEFAULT '{}',
        updated_at  INTEGER NOT NULL,
        PRIMARY KEY (src, dst, edge_type),
        CHECK (src <> dst AND weight >= 0 AND weight <= 1 AND (directed = 1 OR src < dst))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cr_finding_edges_dst ON cr_finding_edges(dst)",
)


def _create_tables(conn: sqlite3.Connection) -> None:
    """Self-create the graph tables (CLI/MCP paths skip ``init_schema``)."""
    for stmt in _CREATE_SQL:
        conn.execute(stmt)


def graph_enabled(conn: sqlite3.Connection) -> bool:
    """Compute kill-switch. Default on; set meta ``findings_graph_enabled='0'`` to disable."""
    return get_meta(conn, _META_ENABLED, "1") != "0"


def ensure_finding_graph(conn: sqlite3.Connection) -> None:
    """Idempotent: create tables, then rebuild if the stored version is stale.

    Called at the top of every graph read and every ``remember`` / ``forget``,
    so an upgraded project whose daemon never applied ``schema.sql`` still gets
    the tables, and a fresh graph on an existing corpus is backfilled exactly
    once (version-stamped, mirroring ``ci_files.parser_version``).

    Runs any needed rebuild in its own transaction when none is open; reuses
    the caller's transaction otherwise. Cheap no-op once the version matches.
    """
    _create_tables(conn)
    if not graph_enabled(conn):
        return
    if get_meta(conn, _META_VERSION) == str(FINDINGS_GRAPH_VERSION):
        return
    if conn.in_transaction:
        rebuild_finding_graph(conn)
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rebuild_finding_graph(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _ensure_quiet(conn: sqlite3.Connection) -> None:
    """``ensure_finding_graph`` for read tools: never raise on a read-only or
    lock-contended DB during the one-time backfill window — just read whatever
    graph already exists."""
    try:
        ensure_finding_graph(conn)
    except Exception:  # pragma: no cover - defensive
        pass


def _mark_dirty(conn: sqlite3.Connection) -> None:
    """Force a full rebuild on the next ``ensure_finding_graph``.

    Used when a swallowed graph-build failure may have left a finding without
    its refs — an edge-only recompute would never restore them, so we schedule
    a one-time repair (which re-extracts every finding's refs)."""
    try:
        set_meta(conn, _META_VERSION, "dirty")
    except Exception:  # pragma: no cover - defensive
        pass


def rebuild_finding_graph(conn: sqlite3.Connection) -> dict:
    """Drop and recompute the entire graph (refs + edges) from scratch.

    Does not manage a transaction — the caller decides boundaries. Also promotes
    ``resolved=0`` refs whose code has since been indexed (re-extraction).
    """
    conn.execute("DELETE FROM cr_finding_refs")
    now_ms = int(time.time() * 1000)
    for row in conn.execute("SELECT id, topic, content FROM cr_findings ORDER BY id").fetchall():
        _insert_refs(conn, int(row["id"]), _ref_text(row["topic"], row["content"]), now_ms)
    recompute_finding_edges(conn)
    set_meta(conn, _META_VERSION, str(FINDINGS_GRAPH_VERSION))
    return {"ok": True}


# ── Refs: finding → code bridge ──────────────────────────────────────

def _ref_text(topic: str, content: str) -> str:
    """Full text to scan — topic + the *entire* content (not the embedded
    ``content[:1024]`` truncation), so a file named past char 1024 still bridges."""
    return f"{topic}\n{content or ''}"


def recompute_finding_refs(conn: sqlite3.Connection, finding_id: int, text: str) -> None:
    """Replace one finding's refs (delete + re-extract). The local, per-node part."""
    conn.execute("DELETE FROM cr_finding_refs WHERE finding_id = ?", (finding_id,))
    _insert_refs(conn, finding_id, text, int(time.time() * 1000))


def _insert_refs(conn: sqlite3.Connection, finding_id: int, text: str, now_ms: int) -> None:
    refs = extract_refs(conn, text)
    if not refs:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO cr_finding_refs"
        "(finding_id, ref_kind, ref_key, file_id, symbol_id, method, resolved, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (finding_id, r["ref_kind"], r["ref_key"], r["file_id"], r["symbol_id"],
             r["method"], r["resolved"], now_ms)
            for r in refs
        ],
    )


def extract_refs(conn: sqlite3.Connection, text: str) -> list[dict]:
    """Resolve a finding's prose to code nodes, language-agnostically.

    Returns dedup'd ref dicts ``{ref_kind, ref_key, file_id, symbol_id, method,
    resolved}``. A ``file`` ref is ``resolved=1`` when a token matches an indexed
    ``ci_files.path``; an unresolved but path-shaped token is kept ``resolved=0``
    so a later rebuild can promote it. A ``symbol`` ref requires qualname-level
    agreement (NULL-qualname matches are skipped) and is always ``resolved=1``.
    """
    if not text:
        return []
    out: dict[tuple[str, str], dict] = {}

    # --- file refs -------------------------------------------------------
    # A bare basename is only bridged when it resolves *unambiguously* — an
    # exact ``path = base`` match, or a single ``.../<base>`` match. Multiple
    # same-basename files (pkg/x/index.ts vs pkg/y/index.ts) are ambiguous, so
    # bridging both would fabricate edges neither finding meant. The LIKE is
    # escaped so ``_`` in snake_case filenames isn't a wildcard.
    for m in _PATH_RE.findall(text):
        base = m.split(":", 1)[0]
        rows = conn.execute(
            "SELECT id, path FROM ci_files WHERE path = ? OR path LIKE ? ESCAPE '\\'",
            (base, f"%/{_like_escape(base)}"),
        ).fetchall()
        exact = [r for r in rows if r["path"] == base]
        if exact:
            chosen = exact
        elif len(rows) == 1:
            chosen = rows
        else:
            chosen = []  # 0 rows, or an ambiguous basename → not a confident bridge
        if chosen:
            for r in chosen:
                out.setdefault(("file", r["path"]), {
                    "ref_kind": "file", "ref_key": r["path"], "file_id": int(r["id"]),
                    "symbol_id": None, "method": "path", "resolved": 1,
                })
        elif not rows and _is_path_shaped(base):
            out.setdefault(("file", base), {
                "ref_kind": "file", "ref_key": base, "file_id": None,
                "symbol_id": None, "method": "path", "resolved": 0,
            })

    # --- symbol refs -----------------------------------------------------
    # A dotted token (``Widget.render``) is trusted when it equals a real
    # qualname. A bare name (``render``) is only trusted when it resolves to a
    # SINGLE symbol — a name shared by several classes is ambiguous, so bridging
    # every homonym would cite symbols the finding never named.
    for token, method in _identifier_tokens(text):
        rows = conn.execute(
            "SELECT s.id, s.qualname, f.path AS path "
            "FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id "
            "WHERE s.qualname = ? OR s.name = ?",
            (token, token),
        ).fetchall()
        if not rows:
            continue
        qual_matches = [r for r in rows if r["qualname"] == token]
        if qual_matches:
            chosen = qual_matches[:K_SYM]  # token IS a qualname (exact agreement)
        elif len(rows) == 1 and rows[0]["qualname"]:
            chosen = rows  # unique name match — safe to bridge
        else:
            continue  # ambiguous bare name, or name-only match → skip (honest)
        for r in chosen:
            if not r["qualname"]:
                continue
            ref_key = f"{r['qualname']}{_KEY_SEP}{r['path']}"
            out.setdefault(("symbol", ref_key), {
                "ref_kind": "symbol", "ref_key": ref_key, "file_id": None,
                "symbol_id": int(r["id"]), "method": method, "resolved": 1,
            })

    return list(out.values())


def _like_escape(s: str) -> str:
    """Escape SQL LIKE metacharacters so filename ``_`` / ``%`` are literals."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_path_shaped(token: str) -> bool:
    """An unresolved token worth persisting: has a directory, or a source ext.

    Blocks prose matches like ``e.g``, ``i.e``, ``Foo.bar`` from becoming refs.
    """
    if "/" in token:
        return True
    ext = token.rsplit(".", 1)[-1].lower() if "." in token else ""
    return ext in _SOURCE_EXTS


def _identifier_tokens(text: str):
    """Yield ``(token, method)`` identifier candidates worth resolving."""
    seen: set[str] = set()
    for backtick, camel in _IDENT_RE.findall(text):
        raw = (backtick or camel).strip().rstrip("()").strip()
        for tok in _split_candidate(raw):
            if _keep_identifier(tok) and tok not in seen:
                seen.add(tok)
                yield tok, "ident"
    for raw in _SNAKE_IDENT_RE.findall(text):
        tok = raw.strip().rstrip("()").strip()
        if _keep_identifier(tok) and tok not in seen:
            seen.add(tok)
            yield tok, "snake"


def _split_candidate(raw: str) -> list[str]:
    """A backtick span may hold a dotted path (``Class.method``) or a bare name."""
    if not raw:
        return []
    parts = [raw]
    if "." in raw and " " not in raw:
        parts.append(raw.rsplit(".", 1)[-1])
    return parts


def _keep_identifier(tok: str) -> bool:
    if not (4 <= len(tok) <= 80):
        return False
    low = tok.lower()
    return low not in _IDENT_STOPWORDS and low not in _SYMBOL_STOPLIST


# ── Edges: finding ↔ finding ─────────────────────────────────────────

def recompute_finding_edges(conn: sqlite3.Connection) -> None:
    """Full recompute of every finding↔finding edge (semantic + shared_*)."""
    conn.execute("DELETE FROM cr_finding_edges")
    now_ms = int(time.time() * 1000)
    edges: list[tuple] = []
    edges += _semantic_edges(conn, now_ms)
    edges += _shared_ref_edges(conn, "file", EDGE_SHARED_FILE, now_ms)
    edges += _shared_ref_edges(conn, "symbol", EDGE_SHARED_SYMBOL, now_ms)
    edges += _shared_tag_edges(conn, now_ms)
    if edges:
        # Sorted insert keeps write order deterministic (aids debugging/diffs).
        edges.sort(key=lambda e: (e[0], e[1], e[2]))
        conn.executemany(
            "INSERT OR REPLACE INTO cr_finding_edges"
            "(src, dst, edge_type, directed, weight, evidence, updated_at)"
            " VALUES (?, ?, ?, 0, ?, ?, ?)",
            edges,
        )


def _edge_row(a: int, b: int, etype: str, weight: float, evidence: dict, now_ms: int) -> tuple:
    src, dst = (a, b) if a < b else (b, a)
    w = round(min(1.0, max(0.0, float(weight))), 4)
    return (src, dst, etype, w, json.dumps(evidence, sort_keys=True), now_ms)


def _semantic_edges(conn: sqlite3.Connection, now_ms: int) -> list[tuple]:
    rows = conn.execute(
        "SELECT id, embedding FROM cr_findings WHERE embedding IS NOT NULL ORDER BY id"
    ).fetchall()
    if len(rows) < 2:
        return []
    if len(rows) > N_SEMANTIC_CAP:
        set_meta(conn, _META_NOTE, f"semantic skipped: N={len(rows)}>cap")
        return []
    set_meta(conn, _META_NOTE, "")
    ids = [int(r["id"]) for r in rows]
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    unit = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)
    sims = unit @ unit.T
    out: list[tuple] = []
    span = 1.0 - SIM_THRESHOLD
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            c = float(sims[i, j])
            if c < SIM_THRESHOLD:
                continue
            weight = (c - SIM_THRESHOLD) / span if span > 0 else 1.0
            out.append(_edge_row(ids[i], ids[j], EDGE_SEMANTIC, weight,
                                  {"cosine": round(c, 3)}, now_ms))
    return out


def _shared_ref_edges(conn: sqlite3.Connection, ref_kind: str, etype: str, now_ms: int) -> list[tuple]:
    """Edges from findings sharing a resolved file/symbol ref_key, IDF-weighted."""
    key_to_fids: dict[str, set[int]] = defaultdict(set)
    for r in conn.execute(
        "SELECT finding_id, ref_key FROM cr_finding_refs WHERE ref_kind = ? AND resolved = 1",
        (ref_kind,),
    ).fetchall():
        key_to_fids[r["ref_key"]].add(int(r["finding_id"]))

    universe: set[int] = set()
    for fids in key_to_fids.values():
        universe |= fids
    n = len(universe)
    if n < 2:
        return []
    use_idf = n >= N_MIN

    # pair -> list of (ref_key, idf) they share
    pair_shared: dict[tuple[int, int], list[tuple[str, float]]] = defaultdict(list)
    for key, fids in key_to_fids.items():
        df = len(fids)
        if df < 2:
            continue
        if use_idf and df / n > 0.5:
            continue  # hub key couples everything to everything — drop
        idf = float(np.log((n + 1) / (df + 0.5)))
        for a, b in combinations(sorted(fids), 2):
            pair_shared[(a, b)].append((key, idf))

    out: list[tuple] = []
    for (a, b), shared in pair_shared.items():
        shared.sort()  # deterministic evidence order regardless of ref insertion order
        if use_idf:
            weight = 1.0 - 0.5 ** sum(idf for _, idf in shared)
        else:
            weight = 1.0 - 0.5 ** len(shared)
        keys = [k for k, _ in shared][:_EVIDENCE_NODE_CAP]
        out.append(_edge_row(a, b, etype, weight, {"keys": keys, "n": len(shared)}, now_ms))
    return out


def _surviving_tags(raw: str | None) -> set[str]:
    """Tags minus synthetic kind:/type: markers and the topical stoplist."""
    try:
        tags = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return set()
    out: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        low = t.strip().lower()
        if not low or low.startswith(("kind:", "type:")) or low in _TAG_STOPLIST:
            continue
        out.add(low)
    return out


def _shared_tag_edges(conn: sqlite3.Connection, now_ms: int) -> list[tuple]:
    finding_tags: dict[int, set[str]] = {}
    for r in conn.execute("SELECT id, tags FROM cr_findings ORDER BY id").fetchall():
        surv = _surviving_tags(r["tags"])
        if surv:
            finding_tags[int(r["id"])] = surv
    n = len(finding_tags)
    if n < 2:
        return []

    tag_to_fids: dict[str, set[int]] = defaultdict(set)
    for fid, tags in finding_tags.items():
        for t in tags:
            tag_to_fids[t].add(fid)

    # Drop hub tags (present in > half of tagged findings) when the corpus is
    # big enough for that ratio to mean anything.
    if n >= N_MIN:
        hubs = {t for t, fids in tag_to_fids.items() if len(fids) / n > 0.5}
        if hubs:
            for fid in finding_tags:
                finding_tags[fid] -= hubs
            for t in hubs:
                tag_to_fids.pop(t, None)

    pair_shared: dict[tuple[int, int], set[str]] = defaultdict(set)
    for t, fids in tag_to_fids.items():
        if len(fids) < 2:
            continue
        for a, b in combinations(sorted(fids), 2):
            pair_shared[(a, b)].add(t)

    out: list[tuple] = []
    for (a, b), shared in pair_shared.items():
        if not shared:
            continue
        union = finding_tags[a] | finding_tags[b]
        weight = len(shared) / len(union) if union else 0.0
        tags = sorted(shared)[:_EVIDENCE_NODE_CAP]
        out.append(_edge_row(a, b, EDGE_SHARED_TAG, weight, {"tags": tags}, now_ms))
    return out


# ── Write hooks (savepoint-guarded; never abort the user's finding) ──

def apply_remember(conn: sqlite3.Connection, finding_id: int, text: str) -> None:
    """Recompute one finding's refs + all edges, inside a ``SAVEPOINT``.

    Called from ``memory.remember`` *inside its open transaction*. On any graph
    error, only the graph work is rolled back — the finding itself still commits.
    """
    conn.execute("SAVEPOINT fg")
    try:
        recompute_finding_refs(conn, finding_id, text)
        recompute_finding_edges(conn)
        conn.execute("RELEASE fg")
    except Exception:  # pragma: no cover - defensive
        conn.execute("ROLLBACK TO fg")
        conn.execute("RELEASE fg")
        # The rollback also discarded this finding's refs; schedule a full
        # repair so it doesn't stay invisible until a manual rebuild.
        _mark_dirty(conn)


def apply_forget(conn: sqlite3.Connection) -> None:
    """Recompute all edges after a finding delete, inside a ``SAVEPOINT``.

    The FK cascade already removed the deleted finding's refs and edges; this
    keeps the remaining findings' IDF-weighted edges consistent.
    """
    conn.execute("SAVEPOINT fg")
    try:
        recompute_finding_edges(conn)
        conn.execute("RELEASE fg")
    except Exception:  # pragma: no cover - defensive
        conn.execute("ROLLBACK TO fg")
        conn.execute("RELEASE fg")
        _mark_dirty(conn)


# ── Read tools ───────────────────────────────────────────────────────

def related_findings(
    conn: sqlite3.Connection,
    topic: str,
    *,
    limit: int = DEFAULT_RELATED_LIMIT,
    min_weight: float = DEFAULT_RELATED_MIN_WEIGHT,
) -> dict:
    """Findings related to *topic*, with per-edge evidence.

    Resolves *topic* by exact match, else the top semantic ``recall`` hit.
    Neighbors are ranked lexicographically: evidence-backed edges
    (``shared_file`` / ``shared_symbol`` / ``shared_tag``, exact) before
    ``semantic`` (approximate), then by weight. Empty rather than guessing.
    """
    _ensure_quiet(conn)
    fid, resolved_topic, note = _resolve_finding(conn, topic)
    if fid is None:
        return {"ok": True, "topic": topic, "neighbors": [], "note": note}

    by_neighbor: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
        "SELECT src, dst, edge_type, weight, evidence FROM cr_finding_edges "
        "WHERE src = ? OR dst = ?",
        (fid, fid),
    ).fetchall():
        other = int(r["dst"]) if int(r["src"]) == fid else int(r["src"])
        if float(r["weight"]) < min_weight:
            continue
        by_neighbor[other].append({
            "type": r["edge_type"],
            "weight": round(float(r["weight"]), 3),
            "evidence": _parse_evidence(r["evidence"]),
        })
    if not by_neighbor:
        return {"ok": True, "topic": resolved_topic, "neighbors": [],
                "note": "no related findings above min_weight"}

    topics = _topics_for(conn, list(by_neighbor))
    neighbors = []
    for nid, edges in by_neighbor.items():
        edges.sort(key=lambda e: (e["type"] not in _EXACT_EDGE_TYPES, -e["weight"]))
        neighbors.append({
            "topic": topics.get(nid, f"#{nid}"),
            "has_exact_link": any(e["type"] in _EXACT_EDGE_TYPES for e in edges),
            "best_weight": max(e["weight"] for e in edges),
            "edges": edges,
        })
    neighbors.sort(key=lambda x: (not x["has_exact_link"], -x["best_weight"], x["topic"]))
    return {
        "ok": True,
        "topic": resolved_topic,
        "edge_coverage": "shared_file/shared_symbol/shared_tag are exact; semantic is approximate",
        "neighbors": neighbors[: max(0, int(limit))],
    }


def file_findings(
    conn: sqlite3.Connection,
    path: str,
    *,
    expand: bool = False,
    limit: int = DEFAULT_FILE_FINDINGS_LIMIT,
    project_root=None,
) -> dict:
    """Durable findings that reference *path* — "what do we already know here?".

    Resolution is index-based (the refs bridge), so it lags a just-deleted file
    until the next reindex. With ``expand``, also pulls findings 1 hop away in
    the graph (edge weight >= 0.4). *path* may be absolute, ``./``-prefixed, or
    project-relative — it is normalized to the project-relative key the refs use.
    """
    _ensure_quiet(conn)
    from ken.search import _normalize_index_path

    target = _normalize_index_path(path, project_root=project_root)
    # Match findings that reference the file directly OR a symbol inside it —
    # a symbol ref_key is "qualname\x1fpath", so its path component (after the
    # char(31) separator) is compared exactly (no LIKE, no escaping needed).
    rows = conn.execute(
        "SELECT DISTINCT f.id, f.topic, f.content, f.updated_at "
        "FROM cr_finding_refs r JOIN cr_findings f ON f.id = r.finding_id "
        "WHERE r.resolved = 1 AND ("
        "  (r.ref_kind = 'file' AND r.ref_key = ?)"
        "  OR (r.ref_kind = 'symbol' AND substr(r.ref_key, instr(r.ref_key, char(31)) + 1) = ?)"
        ") ORDER BY f.updated_at DESC",
        (target, target),
    ).fetchall()
    direct = [
        {"topic": r["topic"], "content": _preview(r["content"])}
        for r in rows[: max(0, int(limit))]
    ]
    result = {"ok": True, "path": target, "findings": direct}
    if not direct:
        result["note"] = "no findings reference this file"
        return result
    if expand:
        seed_ids = [int(r["id"]) for r in rows]
        result["related"] = _expand_neighbors(conn, seed_ids, limit=max(1, int(limit)))
    return result


# ── Read-tool helpers ────────────────────────────────────────────────

def _resolve_finding(conn: sqlite3.Connection, topic: str) -> tuple[int | None, str, str]:
    """(finding_id, resolved_topic, note). Exact topic, else top recall hit."""
    topic = (topic or "").strip()
    if not topic:
        return None, topic, "empty topic"
    row = conn.execute("SELECT id, topic FROM cr_findings WHERE topic = ?", (topic,)).fetchone()
    if row is not None:
        return int(row["id"]), row["topic"], ""
    try:
        from ken.memory import recall

        hits = recall(conn, topic, limit=1)
    except Exception:
        hits = []
    if not hits:
        return None, topic, "no matching finding"
    hit_topic = hits[0]["topic"]
    hrow = conn.execute("SELECT id FROM cr_findings WHERE topic = ?", (hit_topic,)).fetchone()
    if hrow is None:
        return None, topic, "no matching finding"
    return int(hrow["id"]), hit_topic, f"matched by recall to '{hit_topic}'"


def _expand_neighbors(conn: sqlite3.Connection, seed_ids: list[int], *, limit: int) -> list[dict]:
    if not seed_ids:
        return []
    seeds = set(seed_ids)
    found: dict[int, float] = {}
    placeholders = ",".join("?" * len(seed_ids))
    for r in conn.execute(
        f"SELECT src, dst, weight FROM cr_finding_edges "
        f"WHERE (src IN ({placeholders}) OR dst IN ({placeholders})) AND weight >= ?",
        (*seed_ids, *seed_ids, _EXPAND_MIN_WEIGHT),
    ).fetchall():
        for endpoint in (int(r["src"]), int(r["dst"])):
            if endpoint in seeds:
                continue
            found[endpoint] = max(found.get(endpoint, 0.0), round(float(r["weight"]), 3))
    if not found:
        return []
    topics = _topics_for(conn, list(found))
    out = [{"topic": topics.get(nid, f"#{nid}"), "weight": w} for nid, w in found.items()]
    out.sort(key=lambda x: (-x["weight"], x["topic"]))
    return out[:limit]


def _topics_for(conn: sqlite3.Connection, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    return {
        int(r["id"]): r["topic"]
        for r in conn.execute(
            f"SELECT id, topic FROM cr_findings WHERE id IN ({placeholders})", ids
        ).fetchall()
    }


def _parse_evidence(raw: str | None) -> dict:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _preview(content: str | None) -> str:
    text = " ".join((content or "").split())
    return text if len(text) <= _CONTENT_PREVIEW else text[: _CONTENT_PREVIEW - 1].rstrip() + "…"
