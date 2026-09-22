"""Outside-in contracts: what a later session may reuse, and what must change."""

from hashlib import sha256
import json

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.knowledge.context import compact, recall_view, render_brief
from ken.knowledge.dependencies import Fingerprints, assess
from ken.knowledge.records import for_topics
from ken.memory import forget, list_findings, remember
from ken.session_brief import build_session_brief


class FakeEmbedder:
    def embed_passages(self, texts):
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr("ken.memory.get_embedder", FakeEmbedder)
    (tmp_path / ".ken").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/cache.py").write_text("KEY = 'source+rules'\n")
    (tmp_path / "check.txt").write_text("Rule change invalidates the answer: passed\n")
    conn = connect(tmp_path / ".ken/ken.db")
    init_schema(conn)
    yield tmp_path, conn
    conn.close()


def save(conn, **overrides):
    justification = {
        "kind": "decision",
        "rationale": "Different rules may derive different answers from identical text.",
        "evidence": [
            {"path": "check.txt", "note": "Observed result, not a complete proof."}
        ],
        "dependencies": [{"path": "src/cache.py"}],
        "recheck": "Repeat the rule-change regression.",
        **overrides,
    }
    result = remember(
        conn,
        "cache identity",
        "Include rules in the cache key.",
        anchors={"file": "src/cache.py"},
        justification=justification,
    )
    assert result["ok"], result
    return result


def current(conn):
    return list_findings(conn)[0]


def test_second_session_reuses_conclusion_with_evidence_without_reinference(project):
    root, conn = project
    save(conn)
    with connect(root / ".ken/ken.db") as reopened:
        hit = current(reopened)
        assert hit["validity"]["state"] == "unchanged"
        assert hit["justification"]["evidence"][0]["path"] == "check.txt"
        brief = build_session_brief(reopened, project_root=root)
        assert "dependencias sin cambios" in brief
        assert "Include rules" in brief
        assert "Different rules" in brief
        assert "Observed result" not in brief  # evidence stays outside model context


def test_unrelated_edit_preserves_reuse_relevant_edit_demands_review(project):
    root, conn = project
    save(conn)
    (root / "unrelated.txt").write_text("new")
    assert current(conn)["validity"]["state"] == "unchanged"
    (root / "src/cache.py").write_text("KEY = 'source'\n")
    hit = current(conn)
    assert hit["validity"]["state"] == "stale"
    assert hit["validity"]["issues"] == ["src/cache.py"]
    assert "REVISAR" in build_session_brief(conn, project_root=root)


def test_evidence_tamper_is_itself_an_invalidation(project):
    root, conn = project
    save(conn)
    (root / "check.txt").write_text("now says something else")
    assert current(conn)["validity"]["issues"] == ["check.txt"]


def test_new_file_invalidates_an_absence_claim_but_outside_scope_does_not(project):
    root, conn = project
    save(conn, dependencies=[{"kind": "tree", "path": "src", "pattern": "*.py"}])
    (root / "src/readme.md").write_text("not in the search scope")
    assert current(conn)["validity"]["state"] == "unchanged"
    (root / "src/new_caller.py").write_text("use_cache()")
    assert current(conn)["validity"]["state"] == "stale"
    (root / "src/new_caller.py").unlink()
    assert current(conn)["validity"]["state"] == "unchanged"


def test_uncertainty_survives_recall_and_no_dependencies_is_untracked(project):
    root, conn = project
    save(conn, kind="hypothesis", assumptions=["Deployment uses this configuration."])
    brief = build_session_brief(conn, project_root=root)
    assert "hipótesis" in brief and "supuestos pendientes" in brief
    save(conn, dependencies=[], evidence=[])
    assert current(conn)["validity"]["state"] == "untracked"


def test_missing_and_budget_exhaustion_do_not_endorse_reuse(project):
    root, conn = project
    save(conn)
    deps = current(conn)["justification"]["dependencies"]
    assert assess(deps, Fingerprints(root, max_files=0))["state"] == "unknown"
    (root / "src/cache.py").unlink()
    assert current(conn)["validity"]["state"] != "unchanged"


def test_expected_digest_prevents_recording_evidence_that_changed_after_read(project):
    root, conn = project
    save(conn)
    expected = sha256((root / "src/cache.py").read_bytes()).hexdigest()
    (root / "src/cache.py").write_text("new")
    out = remember(
        conn,
        "cache identity",
        "WRONG overwrite",
        justification={
            "rationale": "old observation",
            "dependencies": [{"path": "src/cache.py", "sha256": expected}],
        },
    )
    assert not out["ok"]
    assert current(conn)["content"] == "Include rules in the cache key."


@pytest.mark.parametrize(
    "dependency",
    [
        {"path": "../outside"},
        {"kind": "command", "path": "src/cache.py"},
        {"path": "src/cache.py", "typo": 1},
        {"path": "src/cache.py", "pattern": "*"},
    ],
)
def test_invalid_dependency_is_rejected_atomically(project, dependency):
    _, conn = project
    out = remember(
        conn,
        "bad",
        "bad",
        justification={"rationale": "why", "dependencies": [dependency]},
    )
    assert not out["ok"] and list_findings(conn) == []


def test_plain_overwrite_never_inherits_a_previous_proof_and_forget_cascades(project):
    _, conn = project
    save(conn)
    assert remember(conn, "cache identity", "Different conclusion.")["ok"]
    assert "justification" not in current(conn)
    save(conn)
    assert forget(conn, "cache identity")["ok"]
    assert conn.execute("SELECT COUNT(*) FROM cr_justifications").fetchone()[0] == 0


def test_topic_recall_includes_own_conclusion_even_without_neighbors(project):
    root, conn = project
    save(conn)
    from ken.findings_graph import related_findings

    result = recall_view(
        conn,
        related_findings(conn, "cache identity"),
        root=root,
        detail="full",
        max_chars=3000,
    )
    assert result["finding"]["content"] == "Include rules in the cache key."
    assert result["finding"]["validity"]["state"] == "unchanged"


def test_answer_stage_reads_only_exact_topic_and_preserves_uncertainty(
    project, monkeypatch
):
    root, conn = project
    save(
        conn,
        kind="hypothesis",
        assumptions=["Caller invalidates after changing rules."],
    )
    from ken.mcp import server

    monkeypatch.setattr(server, "_PROJECT_ROOT", root)
    monkeypatch.setattr(
        server,
        "_select_memories",
        lambda *a: pytest.fail("exact answer must not walk related notes"),
    )
    fresh = server.ken_recall(topic="cache identity", detail="answer")
    record = fresh["memories"][0]
    assert record["conclusion"] == "Include rules in the cache key."
    assert record["kind"] == "hypothesis" and record["assumptions"]
    assert record["sources"] and record["expand"]["detail"] == "full"
    assert record["validity"]["state"] == "unchanged"
    assert record["reuse"] == "consider_if_question_and_assumptions_match"
    assert "rationale" not in record
    (root / "src/cache.py").write_text("changed")
    stale = server.ken_recall(topic="cache identity", detail="answer")["memories"][0]
    assert stale["validity"]["state"] == "stale"
    assert stale["reuse"] == "review_inputs_before_reusing"
    assert stale["recheck"]


def test_answer_stage_keeps_whole_conclusions_or_explicit_expansion():
    hit = {
        "topic": "long",
        "content": "A long conclusion. " * 100,
        "validity": {"state": "unknown"},
    }
    for budget in (300, 600, 3000):
        result = compact([hit], budget, detail="answer")
        assert len(json.dumps(result, ensure_ascii=False)) <= budget
        for record in result["memories"]:
            assert (
                record.get("conclusion") == hit["content"]
                or record["conclusion_omitted"]
            )
            assert record["validity"]["state"] == "unknown"


def test_summary_and_automatic_brief_have_hard_budgets_and_live_dedup(project):
    root, conn = project
    save(conn)
    hits = for_topics(conn, ["cache identity"], root=root)
    for budget in (300, 1000, 3000):
        out = compact(hits, budget)
        assert len(json.dumps(out, ensure_ascii=False)) <= budget
        assert len(out["memories"]) + out["omitted"] == 1
    seen = {}
    first = render_brief(conn, ["cache identity"], root=root, seen=seen)
    assert first and len(first) <= 1100
    assert render_brief(conn, ["cache identity"], root=root, seen=seen) == ""
    (root / "src/cache.py").write_text("different")
    assert "REVISAR" in render_brief(conn, ["cache identity"], root=root, seen=seen)


def test_compact_memory_never_silently_clips_the_conclusion_or_its_caveats():
    conclusion = (
        "Observed implementation details. " * 14
        + "This does not guarantee successful chmod at runtime."
    )
    hit = {
        "topic": "permissions",
        "content": conclusion,
        "validity": {"state": "unchanged"},
        "justification": {
            "assumptions": ["Only for the recorded source and environment."],
            "evidence": [{"path": "src/store.py", "note": "Reviewed writer."}],
        },
    }
    full = compact([hit], 3000)["memories"][0]
    assert full["conclusion"] == conclusion
    assert full["conclusion_complete"] is True
    assert full["sources"][0]["path"] == "src/store.py"
    bounded = compact([hit], 300)
    assert len(json.dumps(bounded, ensure_ascii=False)) <= 300
    if bounded["memories"]:
        reference = bounded["memories"][0]
        assert reference["conclusion_omitted"] is True
        assert "conclusion" not in reference
        assert reference["expand"]["detail"] == "full"


def test_symlink_tree_does_not_claim_complete_coverage(project):
    root, conn = project
    (root / "src/linked").symlink_to(root / ".ken", target_is_directory=True)
    out = remember(
        conn,
        "tree",
        "absence",
        justification={
            "rationale": "search",
            "dependencies": [{"kind": "tree", "path": "src", "pattern": "*.py"}],
        },
    )
    assert not out["ok"]


def test_public_mcp_and_cli_use_existing_tools(project, monkeypatch, capsys):
    root, conn = project
    from ken.mcp import server
    from ken.cli import main

    monkeypatch.setattr(server, "_PROJECT_ROOT", root)
    (root / ".ken/meta.json").write_text("{}")
    data = {
        "rationale": "Preserve the rule dependency.",
        "dependencies": [{"path": "src/cache.py"}],
    }
    assert server.ken_remember("api", "Rules belong in the key.", justification=data)[
        "ok"
    ]
    out = server.ken_recall(topic="api", detail="summary", max_chars=1200)
    assert out["memories"][0]["validity"]["state"] == "unchanged"
    assert (
        main(
            [
                "tools",
                "--path",
                str(root),
                "remember",
                "cli",
                "--content",
                "Same contract.",
                "--justification",
                json.dumps(data),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"]
    assert (
        main(
            [
                "tools",
                "--path",
                str(root),
                "recall",
                "--topic",
                "cli",
                "--detail",
                "summary",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["memories"][0]["topic"] == "cli"


def test_prompt_hook_delivers_once_then_warns_on_changed_dependencies(
    project, monkeypatch
):
    root, conn = project
    save(conn)
    from ken.daemon.server import DaemonState, _handle_prompt, HOOK_CONTEXT_MAX_CHARS
    from ken.ranker import FindingItem, RankResult

    monkeypatch.setattr("ken.embedder.get_embedder", FakeEmbedder)
    monkeypatch.setattr(
        "ken.ranker.rank",
        lambda *a, **kw: RankResult(
            findings=[
                FindingItem(
                    "cache identity", "Include rules in the cache key.", score=5.0
                )
            ]
        ),
    )
    state = DaemonState(root, auth_token="test")
    try:
        state.session_start("next-session")
        first = _handle_prompt(state, "next-session", "Improve cache reuse")
        assert "<ken-knowledge>" in first and "dependencias sin cambios" in first
        assert len(first) <= HOOK_CONTEXT_MAX_CHARS
        repeated = _handle_prompt(state, "next-session", "Keep going")
        assert "<ken-knowledge>" not in repeated
        (root / "src/cache.py").write_text("different")
        assert "REVISAR" in _handle_prompt(state, "next-session", "Keep going")
        state.session_start("another-session")
        assert "<ken-knowledge>" in _handle_prompt(
            state, "another-session", "Inspect cache"
        )
    finally:
        state.conn.close()


def test_verbose_rank_cannot_hide_a_stale_memory(project):
    root, conn = project
    save(conn)
    from ken.ranker import FindingItem, RankResult
    from ken.ranker.output import render_block

    result = RankResult(findings=[FindingItem("cache identity", "old text", score=5.0)])
    (root / "src/cache.py").write_text("different")
    assert "REVISAR" in render_block(conn, result, verbose=1)


def test_legacy_database_gains_metadata_without_changing_old_findings(project):
    _, conn = project
    remember(conn, "old", "Unstructured knowledge.")
    conn.execute("DROP TABLE cr_justifications")
    save(conn)
    old = next(h for h in list_findings(conn) if h["topic"] == "old")
    assert old["content"] == "Unstructured knowledge." and "justification" not in old


def test_workspace_alias_is_normalized_without_allowing_internal_symlinks(project):
    root, conn = project
    save(conn)
    alias = root.parent / (root.name + "-alias")
    alias.symlink_to(root, target_is_directory=True)
    deps = current(conn)["justification"]["dependencies"]
    assert assess(deps, Fingerprints(alias))["state"] == "unchanged"
