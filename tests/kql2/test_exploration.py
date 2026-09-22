"""Compiled syntax traversal, without IR lowering or SQL predicate execution."""

import sqlite3

import numpy as np
import pytest

from ken.kql2.exploration.cache import SyntaxCache
from ken.kql2.exploration.expressions import UnsupportedExploration
from ken.kql2.exploration.storage_codec import (
    Dictionary,
    encode_flat,
    flatten,
    validate,
)
from ken.kql2.service import search
from ken.structural.frontend import parser_for


def query(body, select="$n.line"):
    return f'language "kql/2"; module t; query q {{{body} select {select};}}'


def run(root, source, **kwargs):
    return search(root, source, backend="exploration", **kwargs)


@pytest.mark.parametrize(
    "language,name,source",
    [
        ("python", "a.py", 'if x == 3:\n pass\nif y != "a":\n pass\n'),
        ("rust", "a.rs", 'fn f(x:i32) { if x == 3 {} if y != "a" {} }'),
        ("typescript", "a.ts", 'if (x == 3) {} if (y != "a") {}'),
    ],
)
def test_native_scan_equal_legacy_and_full_walk(
    tmp_path, monkeypatch, language, name, source
):
    (tmp_path / name).write_text(source)
    text = query('node $n {kind:"if";}', "$n.start_byte,$n.end_byte")
    expected = search(tmp_path, text, cache_mb=0)
    from ken.kql2 import service

    monkeypatch.setattr(
        service, "lower_source", lambda *a, **k: pytest.fail("legacy lowering used")
    )
    actual = run(tmp_path, text, cache_mb=0)
    reference = run(tmp_path, text, reference=True, cache_mb=0)
    assert actual["rows"] == reference["rows"] == expected["rows"]
    assert actual["analysis"]["scanned_nodes"] == 2
    assert reference["analysis"]["scanned_nodes"] > 2
    assert actual["complete"]


def test_compiled_structure_operators_alternatives_and_captures(tmp_path):
    (tmp_path / "a.py").write_text(
        'if x == 3:\n pass\nif y != "a":\n pass\nif x == y:\n pass\nif 3 == x:\n pass\n'
    )
    text = query(
        """node $n {kind:"if";
      node $condition {kind:"compare"; role:"condition";
        node $left {kind:"identifier";}
        node $right {kind:"literal";}
      }
    } where $condition.operator in ["==","!="];
      where $left.start_byte < $right.start_byte;""",
        "$n.line,$left.name,$right.text",
    )
    actual = run(tmp_path, text, profile=True)
    assert actual["rows"] == [[1, "x", "3"], [3, "y", '"a"']]
    assert actual["complete"]
    assert actual["analysis"]["backend"] == "flatbuffers_exploration"
    assert actual["analysis"]["operator_profile"]


def test_descendant_seed_can_start_at_rare_child_then_walk_ancestors(tmp_path):
    (tmp_path / "a.py").write_text("if x:\n pass\nif y:\n if z:\n  return f()\n")
    text = query(
        'node $n {kind:"if";} node $r {kind:"return";} where contains($n,$r);',
        "$n.line",
    )
    result = run(tmp_path, text)
    assert sorted(result["rows"]) == [[3], [4]]
    assert result["plan"][0][0]["role"] == "r"
    assert result["analysis"]["scanned_nodes"] < 10


def test_states_do_not_mix_files_methods_or_sibling_blocks(tmp_path):
    (tmp_path / "a.py").write_text(
        "def a():\n if x: pass\ndef b():\n return 1\ndef c():\n if y: pass\n return 2\n"
    )
    (tmp_path / "b.py").write_text("def d():\n return 3\n")
    text = query(
        """node $n {kind:"callable";}
      where exists(CodeNode $branch | $branch.kind == "if" and contains($n,$branch));
      where exists(CodeNode $ret | $ret.kind == "return" and contains($n,$ret));
    """,
        "$n.name",
    )
    result = run(tmp_path, text)
    assert result["rows"] == [["c"]]
    assert result["complete"]


def test_negation_is_finalized_at_scope_end(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n return f()\ndef b():\n return 1\n")
    text = query("""node $n {kind:"return";}
      not exists {node $call {kind:"call";} where contains($n,$call);}
    """)
    assert run(tmp_path, text)["rows"] == [[4]]


def test_cache_reuse_growth_deletion_and_path_scope(tmp_path, monkeypatch):
    source = tmp_path / "a.py"
    source.write_text("if x: pass\n")
    (tmp_path / "b.py").write_text("if b: pass\n")
    text = query('node $n {kind:"if";}', "$n.path,$n.line")
    first = run(tmp_path, text)
    assert first["analysis"]["parsed_units"] == 2
    from ken.kql2.exploration import service

    original = service.parser_for
    monkeypatch.setattr(
        service, "parser_for", lambda *a: pytest.fail("unchanged source reparsed")
    )
    assert run(tmp_path, text)["analysis"]["reused_units"] == 2
    monkeypatch.setattr(service, "parser_for", original)
    source.write_text("x=1\nif a: pass\nif b: pass\n")
    changed = run(tmp_path, text)
    assert changed["analysis"]["parsed_units"] == 1
    assert sorted(changed["rows"]) == [["a.py", 2], ["a.py", 3], ["b.py", 1]]
    assert run(tmp_path, text, path="b.py")["rows"] == [["b.py", 1]]
    source.unlink()
    assert run(tmp_path, text)["rows"] == [["b.py", 1]]


@pytest.mark.parametrize(
    "setting,value,reason",
    [
        ("timeout_ms", 0, "timeout"),
        ("max_states", 1, "max_states"),
        ("max_rows", 1, "max_rows"),
    ],
)
def test_budgets_are_visible_and_do_not_poison_cache(tmp_path, setting, value, reason):
    (tmp_path / "a.py").write_text("if x: pass\nif y: pass\n")
    text = query('node $n {kind:"if";}')
    stopped = run(tmp_path, text, **{setting: value})
    assert not stopped["complete"] and stopped["reason"] == reason
    assert run(tmp_path, text)["rows"] == [[1], [2]]


def test_order_limit_union_and_regex(tmp_path):
    (tmp_path / "a.py").write_text("if x: pass\nwhile x: pass\nif y: pass\n")
    text = 'language "kql/2"; module t; query q {node $n {native_kind:/^(if|while)_statement$/;} select $n.line; order by $n.line desc; limit 2;}'
    result = run(tmp_path, text)
    assert result["rows"] == [[3], [2]] and result["results_truncated"]


@pytest.mark.parametrize(
    "body",
    [
        'node $n {namespace:"x";}',
        "callable $n {}",
        "node $n {} node $other {} where same_symbol($n,$other);",
    ],
)
def test_unsupported_semantics_fail_before_io(tmp_path, body):
    with pytest.raises(UnsupportedExploration):
        run(tmp_path, query(body, "1"))
    assert not (tmp_path / ".ken").exists()


def test_parse_errors_survive_reuse_and_prevent_absence_proof(tmp_path):
    (tmp_path / "a.py").write_text("if x == :\n pass\n")
    text = query('not exists {node $n {kind:"yield";}}', "1")
    for _ in range(2):
        result = run(tmp_path, text)
        assert not result["coverage_complete"]
        assert result["rows"] == [] and result["unknown_candidates"] > 0
        assert result["analysis"]["skipped"][0]["reason"] == "parse_error"


def test_flatbuffer_validation_and_read_only_views():
    dictionary = Dictionary()
    source = b"if x: pass\n"
    columns = flatten(parser_for("python", "a.py").parse(source), dictionary)
    blob = encode_flat(columns)
    restored = validate(blob, len(source), len(dictionary.words))
    for old, new in zip(columns, restored):
        np.testing.assert_array_equal(old, new)
        assert not new.flags.writeable
        assert np.shares_memory(new, np.frombuffer(blob, dtype="u1"))
    with pytest.raises(ValueError):
        validate(blob[:20], len(source), len(dictionary.words))
    broken = tuple(c.copy() for c in columns)
    broken[3][1] = 0
    with pytest.raises(ValueError):
        validate(encode_flat(broken), len(source), len(dictionary.words))


def test_publication_rollback_and_reader_snapshot(tmp_path):
    file = tmp_path / "syntax.sqlite"
    cache = SyntaxCache(file, tmp_path)
    source = b"if x: pass\n"
    columns = flatten(parser_for("python", "a.py").parse(source), cache.dictionary)
    unit, _ = cache.put("a.py", "python", "first", "frontend", source, columns)
    cache.snapshot([unit])
    writer = SyntaxCache(file, tmp_path)
    changed = b"if y: pass\nif z: pass\n"
    columns = flatten(parser_for("python", "a.py").parse(changed), writer.dictionary)
    writer.put("a.py", "python", "second", "frontend", changed, columns)
    assert cache.view(unit).source == source
    writer.snapshot([unit])
    assert writer.view(unit).source == changed
    writer.close()
    cache.close()


def test_failed_publication_keeps_old_revision_and_postings(tmp_path):
    cache = SyntaxCache(tmp_path / "syntax.sqlite", tmp_path)
    source = b"if x: pass\n"
    columns = flatten(parser_for("python", "a.py").parse(source), cache.dictionary)
    unit, _ = cache.put("a.py", "python", "old", "v", source, columns)
    old_postings = cache.db.execute("SELECT * FROM postings").fetchall()
    cache.db.execute(
        "CREATE TRIGGER fail_publication BEFORE INSERT ON postings BEGIN SELECT RAISE(ABORT,'injected failure'); END"
    )
    replacement = b"while x: break\n"
    columns = flatten(parser_for("python", "a.py").parse(replacement), cache.dictionary)
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        cache.put("a.py", "python", "new", "v", replacement, columns)
    assert cache.find("a.py", "old", "v") == (unit, 0)
    assert cache.db.execute("SELECT * FROM postings").fetchall() == old_postings
    cache.db.execute("DROP TRIGGER fail_publication")
    cache.put("a.py", "python", "new", "v", replacement, columns)
    assert cache.find("a.py", "new", "v") == (unit, 0)
    cache.close()


def test_scoped_absence_is_closed_despite_unrelated_parse_errors(tmp_path):
    (tmp_path / "a.py").write_text("def good():\n return 1\n")
    (tmp_path / "broken.py").write_text("if x == :\n pass\n")
    text = query(
        'node $n {kind:"return";} not exists {node $c {kind:"call";} where contains($n,$c);}'
    )
    result = run(tmp_path, text)
    assert result["rows"] == [[2]]
    assert result["unknown_candidates"] == 0
    assert not result["coverage_complete"]


@pytest.mark.parametrize("reference", [False, True])
def test_unknown_property_is_not_evidence_for_negation(tmp_path, reference):
    (tmp_path / "a.py").write_text("unknown()\n")
    text = query('not exists {node $n {kind:"identifier";type_kind:"str";}}', "1")
    result = run(tmp_path, text, reference=reference)
    assert result["rows"] == [] and result["unknown_candidates"] == 1


def test_retention_pressure_preserves_complete_query(tmp_path):
    (tmp_path / "a.py").write_text("#" + "x" * 650_000 + "\nif x: pass\n")
    result = run(tmp_path, query('node $n {kind:"if";}'), cache_mb=0.6)
    assert result["rows"] == [[2]] and result["complete"]
    assert result["analysis"]["evicted_units"] == 1
    assert result["analysis"]["allocated_bytes"] <= 600_000


def test_aggregate_identity_and_calculation_barriers(tmp_path):
    (tmp_path / "a.py").write_text("if x: pass\nif y: pass\n")
    result = run(
        tmp_path,
        query(
            "",
            'count(CodeNode $n | $n.kind == "if" | $n), exists(CodeNode $n | $n.kind == "while"), forall(CodeNode $n | $n.kind == "if" | $n.line > 0)',
        ),
    )
    assert result["rows"] == [[2, False, True]]
    failure = run(tmp_path, query("bind $a = 1 / 0; where false;", "$a"))
    assert not failure["complete"] and "division by zero" in failure["reason"]
    assert run(tmp_path, query("where false; bind $a = 1 / 0;", "$a"))["complete"]


def test_containment_inside_or_does_not_restrict_other_alternative(tmp_path):
    (tmp_path / "a.py").write_text("if x: pass\nreturn 1\n")
    text = query(
        'node $n {kind:"if";} node $r {kind:"return";} where contains($n,$r) or $r.line == 2;'
    )
    assert (
        run(tmp_path, text)["rows"]
        == run(tmp_path, text, reference=True)["rows"]
        == [[1]]
    )


def test_union_deduplicates_before_global_order_and_limit(tmp_path):
    text = 'language "kql/2"; module t; query q { {bind $x = 2;} or {bind $x = 2;} or {bind $x = 1;} select $x; order by $x asc; limit 1;}'
    result = run(tmp_path, text)
    assert result["rows"] == [[1]] and result["results_truncated"]


def test_scoped_queries_do_not_issue_sql_per_candidate(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text(
        "\n".join(f"def f{i}():\n return g()" for i in range(200))
    )
    statements = []
    initialize = SyntaxCache.__init__

    def traced(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        self.db.set_trace_callback(statements.append)

    monkeypatch.setattr(SyntaxCache, "__init__", traced)
    text = query(
        'node $n {kind:"return";} where exists(CodeNode $c | $c.kind == "call" and contains($n,$c));'
    )
    result = run(tmp_path, text)
    assert len(result["rows"]) == 200
    assert len([sql for sql in statements if sql.startswith("SELECT")]) < 12


@pytest.mark.parametrize("reference", [False, True])
def test_later_containment_cannot_hide_earlier_arithmetic_error(tmp_path, reference):
    (tmp_path / "a.py").write_text("if x: pass\nreturn 1\n")
    text = query(
        'node $n {kind:"if";} node $r {kind:"return";} bind $x = 1 / 0; where contains($n,$r);'
    )
    result = run(tmp_path, text, reference=reference)
    assert not result["complete"] and "division by zero" in result["reason"]


def test_quantifier_prefilter_cannot_hide_expression_errors(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    text = query("", 'exists(CodeNode $n | 1 / 0 == 0.0 and $n.kind == "return")')
    result = run(tmp_path, text)
    assert not result["complete"] and "division by zero" in result["reason"]


def test_numeric_literal_exponents_do_not_confuse_hex_digits(tmp_path):
    (tmp_path / "a.ts").write_text("const a = 1e3; const b = 0xdead; const c = 1.5;\n")
    result = run(tmp_path, query('node $n {kind:"literal";}', "$n.text,$n.type_kind"))
    assert result["rows"] == [["1e3", "float"], ["0xdead", "int"], ["1.5", "float"]]


def test_nested_unknown_comparison_cannot_certify_absence(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    text = query(
        "",
        'not exists(CodeNode $n | $n.kind == "identifier" and [$n.type_kind] == ["str"])',
    )
    result = run(tmp_path, text)
    assert result["rows"] == [] and result["unknown_candidates"] == 1
