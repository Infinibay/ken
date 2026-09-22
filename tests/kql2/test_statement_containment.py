"""Statement containment: ``inside_try``, ``enclosed_by``, ``handles``, ...

The legacy retry catalogue correlated a loop, a protected region, its handler and the
statement that jumps back by walking ``SYNTAX_PARENT`` and naming raw relations such as
``IN_HANDLER``/``TRY_EXIT_STATUS``/``LOOP_BODY_TAIL``.  These are the KQL 2 spellings of
the same claims: each name states the nesting a pattern means, and the engine reads the
relation the frontend published for that statement.
"""
from __future__ import annotations

from ken.kql2.service import search


SELECTORS = ('callable $unit { } '
             'operation $loop { kind: "loop"; } '
             'operation $protected { kind: "try"; } '
             'operation $handler { } '
             'operation $success { kind: "return"; } '
             'operation $attempt { kind: "call"; } ')

RETRY = ('operation $retry { native_kind: "continue_statement"; } '
         'where inside_handler($retry, $handler); '
         'where continues_to($retry, $loop); ')

CORE = ('where runs($unit, $loop); '
        'where inside_try($success, $protected); '
        'where inside_try($attempt, $protected); '
        'where enclosed_by($success, $loop); '
        'where enclosed_by($protected, $loop); '
        'where handles($handler, $protected); '
        'where exits_cleanly($protected); '
        'where returns_operand($success, $attempt); ')


def query(claims: str) -> str:
    return ('language "kql/2"; module t; query q { '
            + SELECTORS + claims +
            'select $unit, $loop, $protected, $handler, $attempt; }')


def run(tmp_path, source: str, claims: str = CORE + RETRY):
    (tmp_path / 'a.py').write_text(source)
    result = search(tmp_path, query(claims), cache_mb=0)
    assert result['complete'], result
    return result['rows']


LOOP = 'def f():\n while True:\n  try:\n   return work()\n  except Error:\n   continue\n'


def test_the_retry_loop_satisfies_every_containment_claim(tmp_path):
    rows = run(tmp_path, LOOP)
    assert len(rows) == 1, rows
    kinds = {entry.get('kind') for entry in rows[0]}
    native = {entry.get('native_kind') for entry in rows[0]}
    assert {'loop', 'try', 'call'} <= kinds, rows[0]
    assert 'except_clause' in native, rows[0]


def test_a_loop_without_a_protected_attempt_is_not_a_retry(tmp_path):
    # No ``return`` in the protected region: the pattern has nothing that could be
    # handed back on success.
    rows = run(tmp_path, 'def f():\n while True:\n  try:\n   work()\n'
                         '  except Error:\n   continue\n')
    assert rows == [], rows


def test_a_handler_that_leaves_the_loop_is_not_an_explicit_retry(tmp_path):
    # ``break`` leaves the loop instead of jumping back to it: the jump has no target.
    rows = run(tmp_path, LOOP.replace('continue', 'break'))
    assert rows == [], rows


def test_a_finalizer_that_returns_cancels_the_explicit_retry(tmp_path):
    rows = run(tmp_path, LOOP + '  finally:\n   return 1\n')
    assert rows == [], rows


def test_a_finalizer_that_merely_logs_keeps_the_explicit_retry(tmp_path):
    rows = run(tmp_path, LOOP + '  finally:\n   audit()\n')
    assert len(rows) == 1, rows


def test_the_return_must_hand_back_the_call(tmp_path):
    # ``work()`` is a call inside the protected region, but the region returns a
    # constant: the attempt is not what the loop returns.
    rows = run(tmp_path, 'def f():\n while True:\n  try:\n   work()\n   return 1\n'
                         '  except Error:\n   continue\n')
    assert rows == [], rows


def test_the_return_may_wrap_the_call_it_hands_back(tmp_path):
    rows = run(tmp_path, 'async def f():\n while True:\n  try:\n   return await work()\n'
                         '  except Error:\n   continue\n')
    assert len(rows) == 1, rows


def test_a_nested_function_is_not_the_protected_attempt(tmp_path):
    # The inner ``return work()`` runs in its own callable, which no loop encloses.
    rows = run(tmp_path, 'def f():\n while True:\n  try:\n   def g():\n    return work()\n'
                         '  except Error:\n   continue\n')
    assert rows == [], rows


def test_a_statement_after_the_protected_region_is_not_the_loop_tail(tmp_path):
    claims = (CORE + 'where ends_with($loop, $protected); '
              'where falls_through($handler, $protected); ')
    rows = run(tmp_path, 'def f():\n while True:\n  try:\n   return work()\n'
                         '  except Error:\n   pause()\n  audit()\n', claims)
    assert rows == [], rows


def test_a_handler_that_completes_normally_falls_through(tmp_path):
    claims = (CORE.replace('where exits_cleanly($protected); ', '')
              + 'where ends_with($loop, $protected); '
              'where falls_through($handler, $protected); ')
    rows = run(tmp_path, 'def f():\n while True:\n  try:\n   return work()\n'
                         '  except Error:\n   pause()\n', claims)
    assert len(rows) == 1, rows


def test_an_abrupt_handler_does_not_fall_through(tmp_path):
    claims = (CORE + 'where ends_with($loop, $protected); '
              'where falls_through($handler, $protected); ')
    rows = run(tmp_path, LOOP, claims)
    assert rows == [], rows


def test_an_unbound_operand_is_rejected_before_execution(tmp_path):
    # A containment claim names roles: a name the pattern never bound is a typo, not
    # evidence, and the compiler refuses it.
    (tmp_path / 'a.py').write_text(LOOP)
    import pytest
    with pytest.raises(Exception):
        search(tmp_path, query(CORE + 'where inside_try($missing, $protected); '), cache_mb=0)
