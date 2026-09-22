"""Whole-rule outcomes are memoized by (rule text, graph, engine version).

The query text *is* the version: editing a query, or promoting a variant from
``design`` to ``ready``, changes the fingerprint and the older entry is simply
never read again. Editing a file changes the project graph key, so nothing built
from the previous graph can be reused either. That is the whole contract -- a
stored result can only be read when the query and the graph are the same ones.
"""
from __future__ import annotations

from ken.structural import service
from ken.structural.rules import QUERY_CACHE_VERSION, SavedRule, builtin_rules, rule_fingerprint

SOURCE = '''class Glyph:
    def __init__(self, font): self.font = font

class Pool:
    def __init__(self): self.pool = {}
    def key_for(self, state): return state
    def get(self, state):
        key = self.key_for(state)
        if not self.pool.get(key):
            self.pool[key] = Glyph(state)
        return self.pool[key]
'''


def tree(tmp_path, names=("a", "b")):
    for name in names:
        (tmp_path / f"{name}.py").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def counts(result):
    stats = result["analysis"]["query_cache"]
    return stats["hits"], stats["misses"]


def test_a_second_scan_of_an_unchanged_tree_reads_stored_outcomes(tmp_path):
    root = tree(tmp_path)
    first = service.patterns(root, None)
    assert counts(first)[0] == 0 and counts(first)[1] > 0
    second = service.patterns(root, None)
    assert counts(second)[0] == counts(first)[1]
    assert counts(second)[1] == 0
    key = lambda result: sorted((f["id"], f["path"], f["line"], f["variant"]) for f in result["findings"])
    assert key(first) == key(second)
    assert first["complete"] == second["complete"]


def test_editing_one_file_invalidates_every_stored_outcome(tmp_path):
    root = tree(tmp_path)
    service.patterns(root, None)
    (root / "a.py").write_text(SOURCE + "\n# edited\n", encoding="utf-8")
    after = service.patterns(root, None)
    # The graph key changed, so even the rules whose answer did not change must be
    # re-evaluated: a rule's answer is not local to a file ("no class anywhere
    # implements X" depends on all of them).
    assert counts(after) == (0, 23)


def test_a_disabled_cache_stores_nothing(tmp_path):
    root = tree(tmp_path, names=("a",))
    first = service.patterns(root, None, cache_mb=0)
    assert first["analysis"]["query_cache"]["enabled"] is False
    second = service.patterns(root, None, cache_mb=0)
    # Nothing is stored when the cache is off, so nothing is ever a hit; the
    # misses are real evaluations, not cache reads.
    assert counts(second)[0] == 0 and counts(second)[1] > 0


def test_results_can_be_bypassed_without_profiling_or_disabling_the_index(tmp_path):
    root = tree(tmp_path, names=("a",))
    service.patterns(root, ["flyweight"])
    result = service.patterns(root, ["flyweight"], use_result_cache=False)
    assert result["complete"]
    assert result["analysis"]["query_index"]["hit"]
    assert result["analysis"]["query_cache"] == {"enabled": False}
    assert "operator_profile" not in result["outcomes"]["flyweight"]["stats"]


def test_the_rule_text_and_the_engine_version_are_the_version():
    rule = next(r for r in builtin_rules() if r.id == "flyweight")
    base = rule_fingerprint(rule, "strict")
    assert base == rule_fingerprint(rule, "strict")
    assert base != rule_fingerprint(rule, "possible")
    assert base != rule_fingerprint(SavedRule(rule.id, rule.query + "\n# edited"), "strict")
    assert base != rule_fingerprint(SavedRule(rule.id, rule.query, variants=rule.variants + [
        {"id": "extra", "status": "ready", "query": rule.query}]), "strict")
    promoted = SavedRule(rule.id, rule.query,
                         variants=[dict(v, status="design") for v in rule.variants])
    assert base != rule_fingerprint(promoted, "strict")
    assert QUERY_CACHE_VERSION in base


def test_a_bug_scan_is_memoized_too(tmp_path):
    (tmp_path / "bad.py").write_text("def f(values=[]):\n    return values\n", encoding="utf-8")
    first = service.bugs(tmp_path, cache_mb=None)
    assert first["findings"]
    assert counts(first)[1] > 0
    second = service.bugs(tmp_path, cache_mb=None)
    assert counts(second)[0] == counts(first)[1]
    assert [f["id"] for f in first["findings"]] == [f["id"] for f in second["findings"]]


def test_editing_a_matched_saved_rule_invalidates_the_caller(tmp_path):
    """A query that ``match``es a saved rule inherits its meaning.

    The caller's own text does not change when the saved file is rewritten, so
    the fingerprint has to walk the closure of named queries it reaches.
    """
    folder = tmp_path / ".ken" / "rules"
    folder.mkdir(parents=True)
    rule = folder / "selected.toml"
    (tmp_path / "a.py").write_text("def one(): pass\ndef two(): pass\n", encoding="utf-8")
    caller = 'query q { match "team.selected"(f:$f); emit $f; }'
    seen = []
    for name in ("one", "two"):
        rule.write_text(f'id="team.selected"\nquery=\'\'\'query s {{ function(name: "{name}") as $f; emit $f; }}\'\'\'',
                        encoding="utf-8")
        result = service.search(tmp_path, caller)
        seen.append(result["matches"][0]["bindings"]["$f"])
        if len(seen) > 1:
            assert result["analysis"]["query_cache"]["hits"] == 0, "a rewritten saved rule must not hit"
    assert f"CALLABLE:one@" in seen[0] and f"CALLABLE:two@" in seen[1]


def test_exhausted_result_is_retried_with_a_larger_budget(tmp_path):
    from ken.structural.query import QueryBudget

    (tmp_path / 'a.py').write_text('def one(): pass\ndef two(): pass\n')
    query = 'query selected { function() as $f; emit $f; }'
    partial = service.search(tmp_path, query, budget=QueryBudget(max_states=1))
    assert not partial['complete']
    complete = service.search(tmp_path, query)
    assert complete['complete'] and len(complete['matches']) == 2
    assert complete['analysis']['query_cache']['hits'] == 0
    cached = service.search(tmp_path, query)
    assert cached['analysis']['query_cache']['hits'] == 1


def test_cached_complete_result_respects_a_smaller_match_limit(tmp_path):
    from ken.structural.query import QueryBudget

    (tmp_path / 'a.py').write_text('def one(): pass\ndef two(): pass\n')
    query = 'query selected { function() as $f; emit $f; }'
    complete = service.search(tmp_path, query)
    assert len(complete['matches']) == 2
    limited = service.search(tmp_path, query, budget=QueryBudget(max_matches=1))
    assert len(limited['matches']) <= 1
    again = service.search(tmp_path, query)
    assert again['complete'] and len(again['matches']) == 2
