"""Tests for the stochastic (non-LLM) tools: cochange, architecture,
blast_radius, profile, clones, grep, intent_history."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from ken.clones import clones
from ken.cochange import cochange, ingest_commits
from ken.db import connect, init_schema
from ken.graphtools import architecture, blast_radius
from ken.grep import grep
from ken.indexer import index_files
from ken.intent import intent_history
from ken.profile import profile


class _FakeEmbedder:
    @property
    def dim(self) -> int:
        return 384

    def embed_passages(self, texts):
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)

    def _vec(self, text):
        # Bag-of-words: sum per-token random vectors so texts sharing words
        # land near each other (deterministic, model-free).
        v = np.zeros(384, dtype=np.float32)
        for tok in set(text.lower().split()):
            rng = np.random.default_rng(abs(hash(tok)) & 0xFFFF_FFFF)
            v += rng.normal(size=384).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)


@pytest.fixture
def project(tmp_path):
    root = tmp_path
    (root / ".ken").mkdir()
    conn = connect(root / ".ken" / "ken.db")
    init_schema(conn)
    yield root, conn
    conn.close()


def _write_and_index(root, conn, files: dict[str, str], embedder=None):
    rels = []
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        rels.append(Path(rel))
    index_files(conn, root, rels, embedder=embedder)


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init_repo(root):
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "T")


def _commit(root, files: dict[str, str], msg: str):
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", msg)


# --- cochange ---------------------------------------------------------------


def test_cochange_finds_hidden_coupling(project):
    root, conn = project
    _init_repo(root)
    # model.py and migration.sql always change together but never import.
    for i in range(5):
        _commit(root, {"model.py": f"x={i}\n", "migration.sql": f"-- v{i}\n"},
                f"change {i}")
    # an unrelated file changes on its own.
    _commit(root, {"unrelated.py": "y=1\n"}, "noise")

    _write_and_index(root, conn, {
        "model.py": "x=1\n", "migration.sql": "-- v\n", "unrelated.py": "y=1\n",
    })

    res = cochange(conn, "model.py", min_support=3, min_confidence=0.4, project_root=root)
    assert res["ok"]
    partners = {p["path"]: p for p in res["partners"]}
    assert "migration.sql" in partners
    assert partners["migration.sql"]["hidden_coupling"] is True
    assert partners["migration.sql"]["support"] >= 3
    assert "unrelated.py" not in partners


def test_cochange_drops_pairs_that_are_not_significant(project):
    # 20 commits: target in 10, partner in 10, 6 shared. Lift is 1.2 (> 1) and
    # confidence 0.6 (> min), so only the Dunning G² gate can reject it —
    # G² ≈ 0.8, far below χ²(1) at p=0.05.
    root, conn = project
    _init_repo(root)
    n = 0
    for _ in range(6):
        n += 1
        _commit(root, {"target.py": f"a={n}\n", "partner.py": f"b={n}\n"}, f"both {n}")
    for _ in range(4):
        n += 1
        _commit(root, {"target.py": f"a={n}\n"}, f"target {n}")
    for _ in range(4):
        n += 1
        _commit(root, {"partner.py": f"b={n}\n"}, f"partner {n}")
    for _ in range(6):
        n += 1
        _commit(root, {"other.py": f"c={n}\n"}, f"other {n}")
    _write_and_index(root, conn, {
        "target.py": "a=1\n", "partner.py": "b=1\n", "other.py": "c=1\n",
    })

    res = cochange(conn, "target.py", min_support=3, min_confidence=0.4, project_root=root)
    assert [p["path"] for p in res["partners"]] == []

    # Without the significance gate the pair clears every other filter — which
    # is exactly the false positive the gate exists to remove.
    lax = cochange(conn, "target.py", min_support=3, min_confidence=0.4,
                   min_llr=0.0, project_root=root, auto_ingest=False)
    partner = next(p for p in lax["partners"] if p["path"] == "partner.py")
    assert partner["lift"] > 1.0
    assert partner["llr"] < 3.841


def test_cochange_scopes_statistics_to_the_targets_repo(project):
    # Lift is n_ab·N / (n_a·n_b) — linear in N. A sibling repo's commits can
    # never contain the target, so counting them scales every lift.
    root, conn = project
    backend = root / "backend"
    backend.mkdir()
    _init_repo(backend)
    for i in range(5):
        _commit(backend, {"model.py": f"x={i}\n", "schema.sql": f"-- v{i}\n"}, f"c{i}")
    _commit(backend, {"other.py": "z=1\n"}, "noise")

    service = root / "service"
    service.mkdir()
    _init_repo(service)
    for i in range(30):
        _commit(service, {f"m{i}.py": f"{i}\n"}, f"s{i}")

    _write_and_index(root, conn, {
        "backend/model.py": "x=1\n", "backend/schema.sql": "-- v\n",
    })
    ingest_commits(conn, root)  # full workspace ingest: both repos land in cr_commits
    all_commits = conn.execute("SELECT COUNT(*) AS n FROM cr_commits").fetchone()["n"]
    assert all_commits == 36

    res = cochange(conn, "backend/model.py", min_support=3, min_confidence=0.4,
                   project_root=root, auto_ingest=False)
    assert res["scope"] == "backend"
    assert res["total_commits"] == 6  # not 36
    partner = next(p for p in res["partners"] if p["path"] == "backend/schema.sql")
    # 5 shared of 6 backend commits: 5·6/(5·5) = 1.2, not 5·36/(5·5) = 7.2.
    assert partner["lift"] == 1.2


def test_cochange_reports_confidence_lower_bound(project):
    # A 5-of-5 history is not as certain as its point estimate of 1.0 claims;
    # the Wilson bound and the strength it discounts must say so.
    root, conn = project
    _init_repo(root)
    for i in range(5):
        _commit(root, {"model.py": f"x={i}\n", "migration.sql": f"-- v{i}\n"}, f"c{i}")
    _commit(root, {"unrelated.py": "y=1\n"}, "noise")
    _write_and_index(root, conn, {
        "model.py": "x=1\n", "migration.sql": "-- v\n", "unrelated.py": "y=1\n",
    })

    res = cochange(conn, "model.py", min_support=3, min_confidence=0.4, project_root=root)
    partner = next(p for p in res["partners"] if p["path"] == "migration.sql")
    assert partner["confidence"] == 1.0
    assert 0.0 < partner["confidence_low"] < 1.0
    assert partner["strength"] < partner["confidence"]


def test_cochange_empty_without_history(project):
    root, conn = project
    _init_repo(root)
    _commit(root, {"a.py": "1\n"}, "init")
    _write_and_index(root, conn, {"a.py": "1\n"})
    res = cochange(conn, "a.py", project_root=root)
    assert res["ok"]
    assert res["partners"] == []


def test_cochange_workspace_of_repos(project):
    # The indexed root is NOT a repo — it contains sibling repos (backend/,
    # service/), each with its own history. cochange must ingest the repo that
    # holds the queried file and prefix paths with the repo dir.
    root, conn = project
    backend = root / "backend"
    backend.mkdir()
    _init_repo(backend)
    for i in range(5):
        _commit(backend, {"model.py": f"x={i}\n", "schema.sql": f"-- v{i}\n"}, f"c{i}")
    # noise commit so the pair isn't in 100% of commits (keeps lift > 1)
    _commit(backend, {"other.py": "z=1\n"}, "noise")
    # a second, unrelated repo
    service = root / "service"
    service.mkdir()
    _init_repo(service)
    _commit(service, {"main.py": "1\n"}, "init")

    _write_and_index(root, conn, {
        "backend/model.py": "x=1\n",
        "backend/schema.sql": "-- v\n",
        "service/main.py": "1\n",
    })

    res = cochange(conn, "backend/model.py", min_support=3, min_confidence=0.4,
                   project_root=root)
    assert res["ok"]
    partners = {p["path"]: p for p in res["partners"]}
    # paths are prefixed with the repo dir so they match the indexed paths
    assert "backend/schema.sql" in partners
    assert partners["backend/schema.sql"]["hidden_coupling"] is True


def test_ingest_commits_incremental(project):
    root, conn = project
    _init_repo(root)
    _commit(root, {"a.py": "1\n"}, "c1")
    r1 = ingest_commits(conn, root)
    assert r1["ingested"] == 1
    _commit(root, {"a.py": "2\n"}, "c2")
    r2 = ingest_commits(conn, root)
    assert r2["ingested"] == 1  # only the new commit
    total = conn.execute("SELECT COUNT(*) AS n FROM cr_commits").fetchone()["n"]
    assert total == 2


# --- architecture -----------------------------------------------------------


def test_architecture_detects_cycle_and_coverage(project):
    root, conn = project
    _write_and_index(root, conn, {
        "a.py": "import b\n", "b.py": "import a\n", "c.py": "import a\n",
    })
    res = architecture(conn)
    assert res["ok"]
    assert res["edge_coverage"]["resolved"] >= 2
    # a <-> b is a real cycle (cycle entries are size + capped file sample).
    assert any({"a.py", "b.py"} <= set(cyc["files"]) for cyc in res["cycles"])
    hub_paths = {h["path"] for h in res["hubs"]}
    assert "a.py" in hub_paths


def test_architecture_output_is_bounded_by_limit(project):
    root, conn = project
    # A wide fan-in hub plus a long chain: many files across several layers.
    files = {f"m{i}.py": "import hub\n" for i in range(40)}
    files["hub.py"] = "import base\n"
    files["base.py"] = "x = 1\n"
    _write_and_index(root, conn, files)

    res = architecture(conn, depth=1, limit=5)
    # Every list is capped, and layers carry file samples only for `depth` layers.
    assert len(res["hubs"]) <= 5
    assert len(res["sinks"]) <= 5
    assert all("size" in layer for layer in res["layers"])
    detailed = [layer for layer in res["layers"] if "files" in layer]
    assert len(detailed) <= 1  # depth=1
    assert all(len(layer["files"]) <= 5 for layer in detailed)
    # The summary still reports the true totals, not the truncated view.
    assert res["summary"]["graph_files"] >= 41


def test_architecture_reports_cluster_quality(project):
    # Two disjoint import cliques: a partition into them is genuine structure,
    # so Newman Q must land well clear of the 0.3 "meaningful" line.
    root, conn = project
    files = {}
    for group in ("x", "y"):
        for i in range(4):
            peers = "\n".join(f"import {group}{j}" for j in range(4) if j != i)
            files[f"{group}{i}.py"] = peers + "\n"
    _write_and_index(root, conn, files)

    res = architecture(conn)
    quality = res["quality"]
    assert quality["clusters_modularity"] >= 0.3
    assert quality["clusters_meaningful"] is True
    assert quality["pagerank_converged"] is True


def test_modularity_is_near_zero_without_community_structure():
    # A star has no communities to find; label propagation still returns a
    # partition, and Q is what tells the caller not to believe it.
    from ken.graphtools import _modularity

    adj = {0: {i for i in range(1, 12)}}
    everything_together = _modularity([[i for i in range(12)]], adj)
    assert everything_together == 0.0
    each_alone = _modularity([[i] for i in range(12)], adj)
    assert each_alone < 0.05


def test_pagerank_reports_when_it_has_not_converged():
    from ken.graphtools import _pagerank

    # A chain ending in a dangling node needs many sweeps to settle — unlike a
    # symmetric graph, where the uniform start is already stationary.
    nodes = [0, 1, 2, 3, 4]
    adj = {0: {1}, 1: {2}, 2: {3}, 3: {4}}
    _, converged = _pagerank(nodes, adj, iters=3)
    assert converged is False
    settled, converged = _pagerank(nodes, adj, iters=500)
    assert converged is True
    # Rank flows downstream, and the whole vector stays a distribution.
    assert settled[4] > settled[0]
    assert sum(settled.values()) == pytest.approx(1.0, abs=1e-9)


# --- blast_radius -----------------------------------------------------------


def test_blast_radius_reverse_reachability(project):
    root, conn = project
    _write_and_index(root, conn, {
        "core.py": "X=1\n", "mid.py": "import core\n", "top.py": "import mid\n",
    })
    res = blast_radius(conn, "core.py", project_root=root)
    assert res["ok"]
    impacted = {i["path"]: i for i in res["impacted"]}
    assert "mid.py" in impacted and impacted["mid.py"]["hops"] == 1
    assert "top.py" in impacted and impacted["top.py"]["hops"] == 2
    assert "mid.py" in res["direct_importers"]
    assert "lower bound" in res["coverage_note"].lower()


# --- profile ----------------------------------------------------------------


def test_profile_surfaces_distinctive_terms(project):
    root, conn = project
    _write_and_index(root, conn, {
        "auth.py": (
            "def rotate_token():\n    'rotate the auth token'\n    pass\n"
            "def refresh_token():\n    'refresh auth token'\n    pass\n"
        ),
        "render.py": (
            "def draw_pixel():\n    'draw a pixel on canvas'\n    pass\n"
            "def paint_canvas():\n    'paint the canvas'\n    pass\n"
        ),
    })
    res = profile(conn, "auth.py")
    assert res["ok"]
    terms = {t["term"] for t in res["distinguishing_terms"]}
    assert "token" in terms or "auth" in terms
    assert "canvas" not in terms


# --- clones -----------------------------------------------------------------


def test_clones_detects_copy_paste(project):
    root, conn = project
    body = "\n".join(f"    total = total + value_{i} * weight_{i}" for i in range(8))
    dup = f"def compute_alpha(value, weight):\n    total = 0\n{body}\n    return total\n"
    dup2 = f"def compute_beta(value, weight):\n    total = 0\n{body}\n    return total\n"
    _write_and_index(root, conn, {
        "a.py": dup, "b.py": dup2, "c.py": "def tiny():\n    return 1\n",
    })
    res = clones(conn, project_root=root)
    assert res["ok"]
    pairs = res["clones"]
    assert any(
        {p["a"]["file"], p["b"]["file"]} == {"a.py", "b.py"} for p in pairs
    ), pairs


def test_clones_signature_arithmetic_never_overflows():
    # (a*x + b) mod p must agree with exact Python integers. 61-bit constants
    # silently wrap in int64 and stop being a permutation at all.
    from ken.clones import _A, _B, _PRIME, _signature

    shingles = {3, 17, _PRIME - 1, 1_073_741_823, 2_147_483_646}
    got = _signature(shingles).tolist()
    want = [
        min((int(a) * x + int(b)) % _PRIME for x in shingles)
        for a, b in zip(_A.tolist(), _B.tolist())
    ]
    assert got == want


def test_clones_shingles_are_process_independent():
    # Python's hash() is salted per process, which would give a different
    # signature — and different LSH buckets — on every run.
    import subprocess
    import sys

    snippet = (
        "from ken.clones import _shingles;"
        "print(sorted(_shingles('def f(a, b):\\n    return a + b * a - b / a\\n')))"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        ).stdout
        for seed in ("1", "2")
    }
    assert len(runs) == 1, runs


def test_clones_lsh_banding_keeps_recall_at_the_requested_threshold():
    from ken.clones import _TARGET_RECALL, _lsh_params

    for threshold in (0.4, 0.5, 0.6, 0.75, 0.9):
        bands, rows = _lsh_params(threshold)
        recall = 1.0 - (1.0 - threshold**rows) ** bands
        assert recall >= _TARGET_RECALL, (threshold, bands, rows, recall)


def test_clones_similarity_is_exact_not_estimated(project):
    # The reported number must be the true Jaccard of the shingle sets, not
    # the 64-permutation MinHash estimate (stderr ~0.054 around 0.75).
    from ken.clones import _read_lines, _shingles

    root, conn = project
    body = "\n".join(f"    total = total + value_{i} * weight_{i}" for i in range(10))
    _write_and_index(root, conn, {
        "a.py": f"def compute_alpha(value, weight):\n    total = 0\n{body}\n    return total\n",
        "b.py": f"def compute_beta(value, weight):\n    total = 1\n{body}\n    return total\n",
    })
    res = clones(conn, project_root=root, min_similarity=0.5)
    pair = next(p for p in res["clones"] if {p["a"]["file"], p["b"]["file"]} == {"a.py", "b.py"})

    sets = {}
    for rel in ("a.py", "b.py"):
        r = conn.execute(
            "SELECT s.line_start, s.line_end FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id "
            "WHERE f.path = ?", (rel,),
        ).fetchone()
        sets[rel] = _shingles(_read_lines(root, rel, int(r["line_start"]), int(r["line_end"])))
    a, b = sets["a.py"], sets["b.py"]
    assert pair["similarity"] == round(len(a & b) / len(a | b), 3)
    assert pair["containment"] == round(len(a & b) / min(len(a), len(b)), 3)


def test_clones_normalizes_dotted_paths_without_stripping_characters(project):
    # lstrip("./") strips *characters*: ".hidden/mod.py" became "hidden/mod.py".
    root, conn = project
    body = "\n".join(f"    total = total + value_{i} * weight_{i}" for i in range(8))
    fn = f"def compute(value, weight):\n    total = 0\n{body}\n    return total\n"
    _write_and_index(root, conn, {".hidden/mod.py": fn, "copy.py": fn})
    res = clones(conn, ".hidden/mod.py", project_root=root)
    assert res["ok"], res
    assert res["path"] == ".hidden/mod.py"
    assert [c["file"] for c in res["clones"]] == ["copy.py"]


# --- grep -------------------------------------------------------------------


def test_grep_literal_finds_identifier(project):
    root, conn = project
    _write_and_index(root, conn, {
        "conf.py": "MY_ENV_VAR = 'x'\nother = 1\n",
        "use.py": "print(MY_ENV_VAR)\n",
    })
    res = grep(conn, "MY_ENV_VAR", mode="literal", project_root=root)
    assert res["ok"]
    paths = {r["path"] for r in res["results"]}
    assert paths == {"conf.py", "use.py"}


def test_grep_bm25_preserves_identifier(project):
    root, conn = project
    _write_and_index(root, conn, {
        "conf.py": "MY_ENV_VAR = 'x'\n",
        "noise.py": "unrelated = 2\n",
    })
    res = grep(conn, "MY_ENV_VAR", mode="bm25", project_root=root)
    assert res["ok"]
    assert any(r["path"] == "conf.py" for r in res["results"])


# --- intent_history ---------------------------------------------------------


def test_intent_history_routes_by_outcome(project, monkeypatch):
    root, conn = project
    from ken.embedder import vec_to_blob
    import ken.intent as intent_mod

    fake = _FakeEmbedder()
    monkeypatch.setattr(intent_mod, "get_embedder", lambda: fake)

    _write_and_index(root, conn, {"resume.py": "1\n", "other.py": "2\n"})
    now = int(time.time() * 1000)
    conn.execute("INSERT INTO cr_sessions(id, started_at) VALUES (1, ?)", (now,))
    prompt = "fix the session resume bug"
    blob = vec_to_blob(fake.embed_query(prompt))
    conn.execute(
        "INSERT INTO cr_contexts(id, session_id, kind, content, iteration, embedding, created_at) "
        "VALUES (1, 1, 'user_prompt', ?, 0, ?, ?)",
        (prompt, blob, now),
    )
    conn.execute(
        "INSERT INTO cr_interactions(session_id, context_id, iteration, event_type, "
        "target_kind, target_path, weight, created_at) "
        "VALUES (1, 1, 0, 'edit', 'file', 'resume.py', 2.0, ?)",
        (now,),
    )

    res = intent_history(conn, "session resume issue", project_root=root)
    assert res["ok"]
    paths = [f["path"] for f in res["files"]]
    assert "resume.py" in paths
