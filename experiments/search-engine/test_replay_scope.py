"""Scoped restoration preserves full pool identity and rejects accidental omissions."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import replay
from ken.retrieval.model import EntityKey, Passage, Span


@pytest.fixture
def stored(tmp_path, monkeypatch):
    cases, rows, maps, opened = {}, [], {}, []
    for repo in ("a", "b"):
        entity = EntityKey(repo + ".py", "function", "run")
        passages = {
            1: Passage(entity, Span(1, 2), {"body": repo}, "hash-" + repo, Span(1, 6)),
            2: Passage(entity, Span(5, 6), {"body": repo}, "hash-" + repo, Span(1, 6)),
        }
        maps[repo] = passages
        cases[repo] = {"repo_id": repo, "query": "run"}
        rows.append({"id": repo, "candidates": [{"path": entity.path,
            "entity": entity.to_dict(), "signals": {"rrf": .25},
            "passages": [{"start_line": 1, "end_line": 2, "signals": {"lexical": 3.}}]}]})
    (tmp_path / "candidates.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def connect(path):
        opened.append(Path(path).stem)
        return SimpleNamespace(repo=Path(path).stem, close=lambda: None)

    monkeypatch.setattr(replay, "connect", connect)
    monkeypatch.setattr(replay, "init_schema", lambda conn: None)
    monkeypatch.setattr(replay, "load_passage_map", lambda conn: maps[conn.repo])
    return tmp_path, cases, opened


def test_scoped_pool_is_identical_and_opens_only_selected_database(stored):
    folder, cases, opened = stored
    complete = replay.load_pools(folder, cases)
    assert opened == ["a", "b"]
    opened.clear()
    scoped = replay.load_pools(folder, cases, repositories=["b"])
    assert scoped == {"b": complete["b"]}
    assert opened == ["b"]
    assert scoped["b"][0].owned_regions == (Span(1, 2), Span(5, 6))
    assert scoped["b"][0].passages[0].signals == {"lexical": 3.}


@pytest.mark.parametrize("repositories", [[], ["missing"], ["a", "a"], "a", [""], [1], 1, {"a"}])
def test_invalid_scope_fails_before_opening_database(stored, repositories):
    folder, cases, opened = stored
    with pytest.raises(ValueError):
        replay.load_pools(folder, cases, repositories=repositories)
    assert not opened


def test_scope_does_not_hide_unbound_query(stored):
    folder, cases, opened = stored
    del cases["b"]
    with pytest.raises(KeyError):
        replay.load_pools(folder, cases, repositories=["a"])
    assert not opened
