"""Tests for the findings graph: extraction, edge signals, incremental build,
transaction safety, determinism, and the read tools."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from ken.db import connect, get_meta, init_schema, set_meta
from ken.findings_graph import (
    FINDINGS_GRAPH_VERSION,
    ensure_finding_graph,
    extract_refs,
    file_findings,
    rebuild_finding_graph,
    related_findings,
)
from ken.memory import forget, remember


class _FakeEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words land near
    each other; identical texts are identical (cosine 1.0)."""

    @property
    def dim(self) -> int:
        return 384

    def embed_passages(self, texts):
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts):
        return self.embed_passages(texts)

    def embed_query(self, text):
        return self._vec(text)

    def _vec(self, text):
        v = np.zeros(384, dtype=np.float32)
        for tok in set(text.lower().split()):
            rng = np.random.default_rng(abs(hash(tok)) & 0xFFFF_FFFF)
            v += rng.normal(size=384).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)


@pytest.fixture(autouse=True)
def _fake_embedder(monkeypatch):
    monkeypatch.setattr("ken.memory.get_embedder", lambda: _FakeEmbedder())


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "ken.db")
    init_schema(c)
    yield c
    c.close()


def _add_file(conn, path: str) -> int:
    cur = conn.execute(
        "INSERT INTO ci_files(path, content_hash, mtime, indexed_at) VALUES (?, X'00', 0, 0)",
        (path,),
    )
    return int(cur.lastrowid)


def _add_symbol(conn, file_id: int, name: str, qualname: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end) "
        "VALUES (?, 'function', ?, ?, 1, 5)",
        (file_id, name, qualname),
    )
    return int(cur.lastrowid)


def _edges(conn):
    return conn.execute(
        "SELECT src, dst, edge_type, weight FROM cr_finding_edges ORDER BY src, dst, edge_type"
    ).fetchall()


def _refs(conn, topic: str):
    return conn.execute(
        "SELECT r.ref_kind, r.ref_key, r.resolved FROM cr_finding_refs r "
        "JOIN cr_findings f ON f.id = r.finding_id WHERE f.topic = ? "
        "ORDER BY r.ref_kind, r.ref_key",
        (topic,),
    ).fetchall()


# ── Extraction ───────────────────────────────────────────────────────

def test_file_ref_resolves_language_agnostically(conn):
    # .rb is NOT in ranker.channels._KNOWN_EXTS — the bridge must still resolve it.
    _add_file(conn, "lib/widget.rb")
    remember(conn, "ruby parser", "The parser bug lives in lib/widget.rb near the top.")
    rows = _refs(conn, "ruby parser")
    assert ("file", "lib/widget.rb", 1) in [(r["ref_kind"], r["ref_key"], r["resolved"]) for r in rows]


def test_prose_is_not_a_file_ref(conn):
    remember(conn, "notes", "This is prose, e.g. one thing, i.e. another; see Foo.bar somewhere.")
    file_rows = [r for r in _refs(conn, "notes") if r["ref_kind"] == "file"]
    assert file_rows == []


def test_symbol_ref_requires_qualname_and_skips_generics(conn):
    fid = _add_file(conn, "src/widget.py")
    _add_symbol(conn, fid, "render", "Widget.render")
    _add_symbol(conn, fid, "run", "Widget.run")  # generic name, stoplisted
    _add_symbol(conn, fid, "lonely", None)  # NULL qualname — can't satisfy agreement
    remember(conn, "render note", "Call `Widget.render` — not `run`, and `lonely` is irrelevant.")
    keys = {(r["ref_kind"], r["ref_key"]) for r in _refs(conn, "render note")}
    assert ("symbol", "Widget.render\x1fsrc/widget.py") in keys
    assert not any(k[0] == "symbol" and k[1].startswith("Widget.run") for k in keys)  # stoplisted
    assert not any(k[0] == "symbol" and "lonely" in k[1] for k in keys)  # NULL qualname skipped


def test_homonym_symbol_is_not_bridged(conn):
    # Same method name on two classes must NOT bridge on the bare name.
    f1 = _add_file(conn, "src/widget.py")
    _add_symbol(conn, f1, "render", "Widget.render")
    f2 = _add_file(conn, "src/gadget.py")
    _add_symbol(conn, f2, "render", "Gadget.render")
    remember(conn, "w", "fix `render` in the widget flow alpha")
    remember(conn, "g", "rework `render` in the gadget flow beta")
    assert not any(r["ref_kind"] == "symbol" for r in _refs(conn, "w"))  # ambiguous → skipped
    assert [e for e in _edges(conn) if e["edge_type"] == "shared_symbol"] == []
    # A dotted qualname mention is precise and DOES bridge.
    remember(conn, "w2", "the `Widget.render` path specifically")
    assert ("symbol", "Widget.render\x1fsrc/widget.py") in {
        (r["ref_kind"], r["ref_key"]) for r in _refs(conn, "w2")
    }


def test_extract_refs_direct(conn):
    _add_file(conn, "src/auth.py")
    refs = extract_refs(conn, "look at src/auth.py")
    assert refs == [
        {"ref_kind": "file", "ref_key": "src/auth.py", "file_id": _file_id(conn, "src/auth.py"),
         "symbol_id": None, "method": "path", "resolved": 1}
    ]


def _file_id(conn, path):
    return int(conn.execute("SELECT id FROM ci_files WHERE path = ?", (path,)).fetchone()["id"])


# ── Edge signals ─────────────────────────────────────────────────────

def test_ambiguous_basename_is_not_bridged(conn):
    _add_file(conn, "pkg/x/index.ts")
    _add_file(conn, "pkg/y/index.ts")
    remember(conn, "a", "look in index.ts for the x concern alpha")
    remember(conn, "b", "look in index.ts for the y concern beta")
    # bare 'index.ts' matches two files → ambiguous → no resolved ref, no false edge
    assert not any(r["resolved"] == 1 for r in _refs(conn, "a") if r["ref_kind"] == "file")
    assert [e for e in _edges(conn) if e["edge_type"] == "shared_file"] == []
    # An exact path resolves cleanly.
    remember(conn, "c", "the real fix is pkg/x/index.ts specifically gamma")
    assert ("file", "pkg/x/index.ts", 1) in {
        (r["ref_kind"], r["ref_key"], r["resolved"]) for r in _refs(conn, "c")
    }


def test_digit_and_long_extension_resolves(conn):
    # .ps1 / .graphql were dropped by the old [a-zA-Z]{1,5} gate.
    _add_file(conn, "scripts/deploy.ps1")
    _add_file(conn, "api/schema.graphql")
    remember(conn, "ops", "deploy logic is in scripts/deploy.ps1 and api/schema.graphql")
    keys = {(r["ref_key"], r["resolved"]) for r in _refs(conn, "ops") if r["ref_kind"] == "file"}
    assert ("scripts/deploy.ps1", 1) in keys
    assert ("api/schema.graphql", 1) in keys


def test_like_wildcards_are_escaped(conn):
    # '_' in a mentioned-but-unindexed name must not wildcard-match a real file.
    _add_file(conn, "dir/axb.py")
    remember(conn, "n", "the bug is in a_b.py somewhere in the tree")
    file_refs = {(r["ref_key"], r["resolved"]) for r in _refs(conn, "n") if r["ref_kind"] == "file"}
    assert ("dir/axb.py", 1) not in file_refs  # would match if '_' were a wildcard
    assert ("a_b.py", 0) in file_refs  # unmatched but path-shaped → dormant


def test_shared_file_edge(conn):
    _add_file(conn, "src/auth.py")
    # Disjoint wording (no semantic edge) but both cite the same file.
    remember(conn, "alpha", "token expiry handling touches src/auth.py deeply")
    remember(conn, "beta", "logout invalidation path modifies src/auth.py briefly")
    edges = _edges(conn)
    assert any(e["edge_type"] == "shared_file" for e in edges)
    assert all(e["src"] < e["dst"] for e in edges)


def test_semantic_edge_from_similar_content(conn):
    # Identical bodies; topics differ (they're unique) so cosine is high, not 1.0.
    remember(conn, "one", "the quick brown fox jumps over the lazy dog today")
    remember(conn, "two", "the quick brown fox jumps over the lazy dog today")
    edges = [e for e in _edges(conn) if e["edge_type"] == "semantic"]
    assert len(edges) == 1
    assert edges[0]["weight"] > 0.5


def test_no_edge_between_unrelated_findings(conn):
    remember(conn, "aaa", "completely distinct alpha beta gamma delta epsilon")
    remember(conn, "bbb", "unrelated zeta eta theta iota kappa lambda content")
    assert _edges(conn) == []


def test_shared_tag_edge_ignores_synthetic_kind_tags(conn):
    # Same kind (→ same synthetic kind: tag) but no real shared tag ⇒ no edge.
    remember(conn, "k1", "alpha beta gamma", kind="hypothesis")
    remember(conn, "k2", "delta epsilon zeta", kind="hypothesis")
    assert [e for e in _edges(conn) if e["edge_type"] == "shared_tag"] == []
    # A genuine shared tag does link them.
    remember(conn, "t1", "one two three", tags=["auth"])
    remember(conn, "t2", "four five six", tags=["auth"])
    assert any(e["edge_type"] == "shared_tag" for e in _edges(conn))


# ── Transaction safety & lifecycle ───────────────────────────────────

def test_forget_cascades_refs_and_edges(conn):
    _add_file(conn, "src/auth.py")
    remember(conn, "alpha", "src/auth.py token expiry alpha")
    remember(conn, "beta", "src/auth.py logout invalidation beta")
    assert _edges(conn)  # shared_file edge exists
    forget(conn, "alpha")
    assert _refs(conn, "alpha") == []
    assert _edges(conn) == []  # the only edge involved alpha
    assert conn.execute("SELECT COUNT(*) AS n FROM cr_findings").fetchone()["n"] == 1


def test_check_constraint_rejects_bad_edges(conn):
    remember(conn, "a", "one")
    remember(conn, "b", "two")
    ids = [int(r["id"]) for r in conn.execute("SELECT id FROM cr_findings ORDER BY id")]
    lo, hi = min(ids), max(ids)
    with pytest.raises(sqlite3.IntegrityError):  # self-loop
        conn.execute("INSERT INTO cr_finding_edges VALUES (?,?,?,0,0.5,'{}',0)", (lo, lo, "semantic"))
    with pytest.raises(sqlite3.IntegrityError):  # non-canonical undirected (src>dst)
        conn.execute("INSERT INTO cr_finding_edges VALUES (?,?,?,0,0.5,'{}',0)", (hi, lo, "semantic"))
    with pytest.raises(sqlite3.IntegrityError):  # weight out of range
        conn.execute("INSERT INTO cr_finding_edges VALUES (?,?,?,0,1.5,'{}',0)", (lo, hi, "semantic"))


def test_savepoint_isolation_keeps_finding_on_graph_failure(conn, monkeypatch):
    ensure_finding_graph(conn)  # stamp version so remember's ensure is a no-op

    def boom(_conn):
        raise RuntimeError("edge build blew up")

    monkeypatch.setattr("ken.findings_graph.recompute_finding_edges", boom)
    out = remember(conn, "resilient", "this must survive a graph failure")
    assert out["ok"] is True
    assert conn.execute("SELECT COUNT(*) AS n FROM cr_findings WHERE topic='resilient'").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM cr_finding_edges").fetchone()["n"] == 0
    assert _refs(conn, "resilient") == []  # rolled back with the savepoint


def test_kill_switch_disables_graph(conn):
    set_meta(conn, "findings_graph_enabled", "0")
    _add_file(conn, "src/auth.py")
    remember(conn, "off", "src/auth.py should not be bridged")
    assert conn.execute("SELECT COUNT(*) AS n FROM cr_finding_refs").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM cr_finding_edges").fetchone()["n"] == 0


def test_backfill_builds_graph_for_preexisting_findings(conn):
    # Insert findings directly (bypassing remember → no graph), then ensure.
    _add_file(conn, "src/auth.py")
    emb = _FakeEmbedder()
    for topic, content in [("x", "auth src/auth.py alpha"), ("y", "auth src/auth.py beta")]:
        vec = np.ascontiguousarray(emb.embed_query(f"{topic}\n\n{content}"), dtype=np.float32).tobytes()
        conn.execute(
            "INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at) "
            "VALUES (?, ?, '[]', ?, 0, 0)",
            (topic, content, vec),
        )
    assert get_meta(conn, "findings_graph_version") is None
    ensure_finding_graph(conn)
    assert get_meta(conn, "findings_graph_version") == str(FINDINGS_GRAPH_VERSION)
    assert any(e["edge_type"] == "shared_file" for e in _edges(conn))


def test_unresolved_ref_promoted_on_rebuild(conn):
    remember(conn, "future", "the fix will land in src/future.py eventually")
    row = _refs(conn, "future")
    assert ("file", "src/future.py", 0) in [(r["ref_kind"], r["ref_key"], r["resolved"]) for r in row]
    # Now index the file and rebuild → the ref is promoted, file_findings sees it.
    _add_file(conn, "src/future.py")
    conn.execute("BEGIN IMMEDIATE")
    rebuild_finding_graph(conn)
    conn.execute("COMMIT")
    assert ("file", "src/future.py", 1) in [
        (r["ref_kind"], r["ref_key"], r["resolved"]) for r in _refs(conn, "future")
    ]
    result = file_findings(conn, "src/future.py")
    assert [f["topic"] for f in result["findings"]] == ["future"]


# ── Determinism ──────────────────────────────────────────────────────

def _build_corpus(db_path, order):
    c = connect(db_path)
    init_schema(c)
    _add_file(c, "src/auth.py")
    _add_file(c, "src/db.py")
    corpus = {
        "a": "auth token src/auth.py alpha",
        "b": "auth logout src/auth.py beta",
        "c": "database pool src/db.py gamma",
        "d": "auth token src/auth.py alpha",  # identical body to a → semantic + shared_file
    }
    for topic in order:
        remember(c, topic, corpus[topic], tags=["auth"] if topic in "abd" else ["data"])
    # Map edges to topic-keyed tuples (ids are insertion-order dependent).
    id_topic = {int(r["id"]): r["topic"] for r in c.execute("SELECT id, topic FROM cr_findings")}
    out = set()
    for e in c.execute("SELECT src, dst, edge_type, weight FROM cr_finding_edges"):
        ts = tuple(sorted((id_topic[int(e["src"])], id_topic[int(e["dst"])])))
        out.add((ts[0], ts[1], e["edge_type"], round(float(e["weight"]), 4)))
    c.close()
    return out


def test_graph_is_order_independent(tmp_path):
    g1 = _build_corpus(tmp_path / "a.db", ["a", "b", "c", "d"])
    g2 = _build_corpus(tmp_path / "b.db", ["d", "c", "b", "a"])
    g3 = _build_corpus(tmp_path / "c.db", ["c", "a", "d", "b"])
    assert g1 == g2 == g3
    assert g1  # non-trivial: some edges exist


# ── Read tools ───────────────────────────────────────────────────────

def test_related_findings_ranks_exact_before_semantic(conn):
    _add_file(conn, "src/auth.py")
    remember(conn, "seed", "auth token src/auth.py alpha")
    remember(conn, "shares-file", "auth logout src/auth.py beta")  # shared_file (exact)
    remember(conn, "shares-words", "auth token src/auth.py alpha")  # identical → semantic + shared_file
    out = related_findings(conn, "seed")
    assert out["ok"] is True
    topics = [n["topic"] for n in out["neighbors"]]
    assert set(topics) == {"shares-file", "shares-words"}
    assert all(n["has_exact_link"] for n in out["neighbors"])  # both share the file


def test_related_findings_empty_when_no_match(conn):
    remember(conn, "solo", "alpha beta gamma unique words")
    out = related_findings(conn, "solo")
    assert out["neighbors"] == []


def test_file_findings_and_expand(conn):
    _add_file(conn, "src/auth.py")
    remember(conn, "direct", "src/auth.py token expiry alpha")
    remember(conn, "neighbor", "src/auth.py logout beta")  # linked via shared_file
    out = file_findings(conn, "./src/auth.py")  # ./ prefix must normalize
    assert {f["topic"] for f in out["findings"]} == {"direct", "neighbor"}
    out_expand = file_findings(conn, "src/auth.py", expand=True)
    assert "related" in out_expand


def test_file_findings_includes_symbol_refs_into_the_file(conn):
    fid = _add_file(conn, "src/widget.py")
    _add_symbol(conn, fid, "render", "Widget.render")
    remember(conn, "sym note", "the `Widget.render` path needs work")  # symbol ref, not a file ref
    out = file_findings(conn, "src/widget.py")
    assert [f["topic"] for f in out["findings"]] == ["sym note"]


def test_file_findings_empty(conn):
    out = file_findings(conn, "src/nonexistent.py")
    assert out["findings"] == []
    assert "note" in out


def test_file_findings_normalizes_absolute_path(conn, tmp_path):
    _add_file(conn, "src/auth.py")
    remember(conn, "note", "auth token handling in src/auth.py")
    abs_path = str(tmp_path / "src" / "auth.py")
    out = file_findings(conn, abs_path, project_root=tmp_path)
    assert [f["topic"] for f in out["findings"]] == ["note"]


def test_limit_zero_returns_empty(conn):
    _add_file(conn, "src/auth.py")
    remember(conn, "a", "src/auth.py token expiry alpha")
    remember(conn, "b", "src/auth.py logout invalidation beta")
    assert file_findings(conn, "src/auth.py", limit=0)["findings"] == []
    assert related_findings(conn, "a", limit=0)["neighbors"] == []


def test_dirty_marker_triggers_repair_after_graph_failure(conn, monkeypatch):
    ensure_finding_graph(conn)  # stamp version

    calls = {"n": 0}
    real_edges = __import__("ken.findings_graph", fromlist=["recompute_finding_edges"]).recompute_finding_edges

    def flaky(c):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient blowup")
        return real_edges(c)

    _add_file(conn, "src/auth.py")
    monkeypatch.setattr("ken.findings_graph.recompute_finding_edges", flaky)
    remember(conn, "hurt", "src/auth.py alpha")  # graph build fails → refs rolled back, marked dirty
    assert _refs(conn, "hurt") == []
    assert get_meta(conn, "findings_graph_version") == "dirty"
    # Next write repairs everything (full rebuild re-extracts all refs).
    remember(conn, "heal", "src/auth.py beta")
    assert any(r["resolved"] == 1 for r in _refs(conn, "hurt"))  # repaired
    assert get_meta(conn, "findings_graph_version") == str(FINDINGS_GRAPH_VERSION)
