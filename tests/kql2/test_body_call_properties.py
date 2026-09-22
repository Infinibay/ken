"""Call-occurrence properties: ``resolution:`` and ``discarded: true;``.

The legacy catalogue stated these two facts with the ``ENTITY``(CALL) attributes and
the ``DISCARDS_RESULT`` relation.  Clauses carry them now:

* ``call $c { discarded: true; }`` — the result of this call is not consumed, the
  statement that holds it throws it away (``DISCARDS_RESULT(statement, call)``).
* ``call $c { name: "clone"; }`` — the callee spelling the occurrence publishes.
* ``call $c { resolution: resolved|unresolved|ambiguous; }`` — the analysis status of
  the callee, as the semantic layer publishes it on every call occurrence. A
  ``resolution:`` clause binds the occurrence itself when no declared callable
  accredits it, so an unresolved call can be stated (the Rust ``derive(Clone)`` shape).
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(constraints: str, callable_name: str = 'f') -> str:
    return ('language "kql/2"; module t; query q { '
            f'callable $f {{ name: "{callable_name}"; body {{ '
            f'call $c {{ {constraints} }} as $call; '
            '} } select $f; }')


SOURCE = ('def g():\n'
          '    return 1\n'
          'def f():\n'
          '    g()\n'
          '    return 0\n')

RETURNED = ('def g():\n'
            '    return 1\n'
            'def f():\n'
            '    return g()\n')

ASSIGNED = ('def g():\n'
            '    return 1\n'
            'def f():\n'
            '    x = g()\n'
            '    return x\n')

UNDEFINED = ('def f():\n'
             '    g()\n'
             '    return 0\n')


def run(tmp_path, source: str, constraints: str):
    (tmp_path / 'a.py').write_text(source)
    return search(tmp_path, query(constraints), cache_mb=0)


def test_discarded_matches_a_call_whose_result_the_statement_drops(tmp_path):
    result = run(tmp_path, SOURCE, 'discarded: true;')
    assert result['complete'] and len(result['rows']) == 1, result


def test_discarded_rejects_a_returned_result(tmp_path):
    result = run(tmp_path, RETURNED, 'discarded: true;')
    assert result['complete'] and result['rows'] == [], result


def test_discarded_rejects_an_assigned_result(tmp_path):
    result = run(tmp_path, ASSIGNED, 'discarded: true;')
    assert result['complete'] and result['rows'] == [], result


def test_discarded_requires_true(tmp_path):
    # The default is that the result is consumed, so only ``true`` is a statement;
    # ``false`` would be spelling the absence of the very evidence being asked for.
    (tmp_path / 'a.py').write_text(SOURCE)
    with pytest.raises(Exception):
        search(tmp_path, query('discarded: false;'), cache_mb=0)


def test_resolution_matches_a_resolved_call(tmp_path):
    result = run(tmp_path, SOURCE, 'resolution: resolved;')
    assert result['complete'] and len(result['rows']) == 1, result


def test_resolution_rejects_a_call_resolved_to_another_status(tmp_path):
    result = run(tmp_path, SOURCE, 'resolution: ambiguous;')
    assert result['complete'] and result['rows'] == [], result


def test_resolution_requires_a_known_status(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    with pytest.raises(Exception):
        search(tmp_path, query('resolution: maybe;'), cache_mb=0)


def test_unresolved_call_matches_the_occurrence_it_cannot_accredit(tmp_path):
    # ``g`` is never defined, so no callable accredits the callee. The clause still
    # binds the occurrence: the status it states is evidence about the call itself.
    result = run(tmp_path, UNDEFINED, 'name: "g"; resolution: unresolved;')
    assert result['complete'] and len(result['rows']) == 1, result


def test_unresolved_call_rejects_the_resolved_status(tmp_path):
    result = run(tmp_path, UNDEFINED, 'resolution: resolved;')
    assert result['complete'] and result['rows'] == [], result


def test_resolved_call_rejects_the_unresolved_status(tmp_path):
    result = run(tmp_path, SOURCE, 'resolution: unresolved;')
    assert result['complete'] and result['rows'] == [], result


def test_name_matches_the_callee_spelling(tmp_path):
    result = run(tmp_path, SOURCE, 'name: "g";')
    assert result['complete'] and len(result['rows']) == 1, result


def test_name_rejects_another_callee_spelling(tmp_path):
    result = run(tmp_path, SOURCE, 'name: "h";')
    assert result['complete'] and result['rows'] == [], result


def test_name_requires_a_literal(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    with pytest.raises(Exception):
        search(tmp_path, query('name: g;'), cache_mb=0)
