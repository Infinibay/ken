"""Resolved calls compose with scoped absence without weakening the question."""

import pytest

from ken.kql2 import parse
from ken.kql2.compiler import CompileError, compile
from ken.kql2.service import search

HEADER = 'language "kql/2"; module investigation; '
SOURCE = """def _conn(): pass
def leak():
    conn = _conn()
def closed():
    conn = _conn()
    conn.close()
def wrapped():
    with closing(_conn()) as conn:
        pass
def returned():
    return _conn()
def nested():
    conn = _conn()
    def later():
        conn.close()
"""
QUERY = """query q {
  callable $target { name: "_conn"; }
  callable $owner {
    call $open { target: $target; }
    not exists { call $close { name: /^(close|closing)$/; } }
  }
  select $owner;
}"""


@pytest.mark.parametrize("reference", [False, True])
def test_resolved_target_and_scoped_absence(tmp_path, reference):
    (tmp_path / "a.py").write_text(SOURCE)
    result = search(tmp_path, HEADER + QUERY, reference=reference, cache_mb=0)
    assert result["complete"] and not result["unknown_candidates"], result
    assert {row[0].split("CALLABLE:")[1].split("@")[0] for row in result["rows"]} == {
        "leak",
        "returned",
        "nested",
    }


def test_negative_resolved_targets_remain_open_world(tmp_path):
    (tmp_path / "a.py").write_text("def close(): pass\ndef f(conn): conn.close()\n")
    query = """query q {
      callable $target {name:"close";}
      callable $owner {not exists {call $c {target:$target;}}}
      select $owner;
    }"""
    result = search(tmp_path, HEADER + query, cache_mb=0)
    assert not result["rows"] and result["unknown_candidates"] > 0


@pytest.mark.parametrize("keyword", ["not exists", "optional"])
def test_local_witnesses_are_private(keyword):
    query = QUERY.replace("not exists", keyword).replace(
        "select $owner;", "select $close;"
    )
    with pytest.raises(CompileError, match="not bound"):
        compile(parse(HEADER + query))


def test_optional_and_alternatives_compose(tmp_path):
    (tmp_path / "a.py").write_text(SOURCE)
    query = QUERY.replace(
        "not exists { call $close { name: /^(close|closing)$/; } }",
        """
      optional { call $close {name:"close";} }
      not exists {
        either {call $end {name:"close";}} or {call $end {name:"closing";}}
      }""",
    )
    result = search(tmp_path, HEADER + query, cache_mb=0)
    assert len(result["rows"]) == 3 and not result["unknown_candidates"]


def test_global_negation_explains_how_to_supply_a_scope():
    with pytest.raises(CompileError, match="inside a source selector"):
        compile(
            parse(
                HEADER
                + """query q {
          callable $target {name:"close";}
          not exists {call $c {target:$target;}}
          select $target;
        }"""
            )
        )


def test_later_alias_cannot_capture_a_private_witness(tmp_path):
    (tmp_path / "a.py").write_text(SOURCE)
    query = QUERY.replace(
        "select $owner;", "bind $close = $target; select $owner,$close;"
    )
    result = search(tmp_path, HEADER + query, cache_mb=0)
    assert len(result["rows"]) == 3


def test_compact_evidence_keeps_source_anchors_without_repeating_proof_edges(tmp_path):
    from ken.checks.report import query_view
    (tmp_path / 'a.py').write_text(SOURCE)
    result = search(tmp_path, HEADER + QUERY, cache_mb=0)
    compact = query_view(result)
    assert compact['rows'] == result['rows']
    assert compact['evidence'][0]['sources']
    assert 'TARGET' in compact['evidence'][0]['relations']
    assert 'optional_evidence' not in compact
    assert query_view(result, full=True)['optional_evidence'][0]['evidence']
